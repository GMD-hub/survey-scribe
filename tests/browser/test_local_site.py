"""Chromium interaction and deterministic WCAG checks for the generated site."""

from __future__ import annotations

from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, Page, Route, ViewportSize, sync_playwright

_IMPORTANT_ROUTES = (
    "index.md",
    "getting-started/installation.md",
    "getting-started/quickstart.md",
    "cli.md",
    "migration.md",
    "playground.md",
    "guides/configuration.md",
    "guides/security.md",
    "guides/sources.md",
    "sources/xlsform.md",
    "guides/results.md",
    "guides/custom-models.md",
    "guides/privacy.md",
    "reference/index.md",
    "reference/providers.md",
    "reference/schemas.md",
)
_LOCAL_ORIGIN = "http://survey-scribe.test"
_AXE = Axe()


def _site_file(site: Path, markdown_path: str) -> Path:
    relative = Path(markdown_path)
    if relative.name == "index.md":
        return site / relative.parent / "index.html"
    return site / relative.with_suffix("") / "index.html"


def _site_url(markdown_path: str) -> str:
    relative = Path(markdown_path)
    if relative.name == "index.md":
        path = "" if relative.parent == Path(".") else relative.parent.as_posix().strip("/")
    else:
        path = relative.with_suffix("").as_posix()
    return f"{_LOCAL_ORIGIN}/{path + '/' if path else ''}"


def _all_navigation_routes(repository_root: Path) -> tuple[str, ...]:
    configuration = yaml.safe_load((repository_root / "mkdocs.yml").read_text(encoding="utf-8"))
    routes: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            routes.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(configuration["nav"])
    return tuple(routes)


def _new_page(
    browser: Browser,
    site: Path,
    viewport: ViewportSize,
) -> tuple[Page, list[str]]:
    page = browser.new_page(viewport=viewport)
    network_routes: list[str] = []

    def serve_generated_site(route: Route) -> None:
        split = urlsplit(route.request.url)
        if f"{split.scheme}://{split.netloc}" != _LOCAL_ORIGIN:
            network_routes.append(route.request.url)
            route.abort()
            return
        relative = unquote(split.path).lstrip("/")
        target = site / relative
        if split.path.endswith("/"):
            target /= "index.html"
        try:
            target.resolve().relative_to(site.resolve())
        except ValueError:
            route.fulfill(status=403, body="forbidden")
            return
        if not target.is_file():
            route.fulfill(status=404, body="not found")
            return
        content_type = guess_type(target.name)[0] or "application/octet-stream"
        route.fulfill(path=target, content_type=content_type)

    page.route("**/*", serve_generated_site)
    return page, network_routes


def _audit_page(page: Page, *, require_playground: bool = False) -> list[str]:
    return page.evaluate(
        """
        ({ requirePlayground }) => {
          const failures = [];
          const main = document.querySelector("main");
          if (document.documentElement.lang !== "en") failures.push("html-lang");
          if (!main) return ["main-landmark"];
          if (main.querySelectorAll("h1").length !== 1) failures.push("one-main-h1");

          const ids = Array.from(document.querySelectorAll("[id]")).map((node) => node.id);
          if (new Set(ids).size !== ids.length) failures.push("unique-ids");
          document.querySelectorAll("img").forEach((image) => {
            if (!image.hasAttribute("alt")) failures.push("image-alt");
          });
          document.querySelectorAll("a[href], button").forEach((control) => {
            if (control.id.startsWith("__codelineno-") || control.getAttribute("aria-hidden") === "true") {
              return;
            }
            const name = control.getAttribute("aria-label") ||
              control.getAttribute("title") ||
              control.textContent.trim();
            if (!name) failures.push("control-name");
          });
          document.querySelectorAll("input, textarea, select").forEach((control) => {
            if (control.offsetParent === null) return;
            const labelled = control.getAttribute("aria-label") ||
              control.getAttribute("aria-labelledby") ||
              (control.id && document.querySelector(`label[for='${control.id}']`)) ||
              control.closest("label");
            if (!labelled) failures.push("form-label");
          });

          let previous = 0;
          main.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((heading) => {
            const level = Number(heading.tagName.substring(1));
            if (previous && level > previous + 1) failures.push("heading-order");
            previous = level;
          });
          if (document.documentElement.scrollWidth > window.innerWidth + 1) {
            failures.push("viewport-overflow");
          }

          if (requirePlayground) {
            const playground = main.querySelector("[data-static-playground]");
            if (!playground) failures.push("playground-region");
            if (playground && playground.querySelectorAll("[role='tab']").length !== 3) {
              failures.push("playground-tabs");
            }
            if (!playground || playground.querySelectorAll("input, textarea, select, form").length) {
              failures.push("playground-input-policy");
            }
            const chip = playground && playground.querySelector("[data-status]");
            if (chip) {
              const rgb = (value) => value.match(/[0-9.]+/g).slice(0, 3).map(Number);
              const luminance = (value) => {
                const components = rgb(value).map((part) => {
                  const channel = part / 255;
                  return channel <= 0.03928
                    ? channel / 12.92
                    : Math.pow((channel + 0.055) / 1.055, 2.4);
                });
                return 0.2126 * components[0] + 0.7152 * components[1] + 0.0722 * components[2];
              };
              const style = getComputedStyle(chip);
              const foreground = luminance(style.color);
              const background = luminance(style.backgroundColor);
              const ratio = (Math.max(foreground, background) + 0.05) /
                (Math.min(foreground, background) + 0.05);
              if (ratio < 4.5) failures.push("playground-status-contrast");
            }
          }
          return Array.from(new Set(failures));
        }
        """,
        {"requirePlayground": require_playground},
    )


def _serious_axe_violations(page: Page) -> list[str]:
    results = _AXE.run(
        page,
        options={
            "resultTypes": ["violations"],
            "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]},
        },
    )
    assert results.response["testEngine"] == {"name": "axe-core", "version": "4.12.1"}
    return [
        f"{violation['id']} ({violation['impact']}): "
        + ", ".join(str(node["target"]) for node in violation["nodes"])
        for violation in results.response["violations"]
        if violation.get("impact") in {"serious", "critical"}
    ]


def _assert_local_page(
    page: Page,
    path: Path,
    url: str,
    network_routes: list[str],
) -> None:
    assert path.is_file()
    page.goto(url, wait_until="load")
    assert page.title().endswith("Survey Scribe")
    assert page.locator("main").is_visible()
    storage = page.evaluate(
        "({local: Object.keys(localStorage), session: Object.keys(sessionStorage), "
        "cookie: document.cookie})"
    )
    assert storage == {"local": [], "session": [], "cookie": ""}
    assert network_routes == []


def test_every_navigation_route_loads_from_generated_site(repository_root: Path) -> None:
    site = repository_root / "site"
    if not (site / "index.html").is_file():
        pytest.skip("build the MkDocs site before browser tests")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page, network_routes = _new_page(browser, site, {"width": 1440, "height": 900})
        for route in _all_navigation_routes(repository_root):
            _assert_local_page(
                page,
                _site_file(site, route),
                _site_url(route),
                network_routes,
            )
        browser.close()


@pytest.mark.parametrize(
    "viewport",
    (
        {"width": 1440, "height": 900},
        {"width": 390, "height": 844},
    ),
    ids=("desktop", "mobile"),
)
def test_important_routes_pass_deterministic_wcag_audit(
    repository_root: Path,
    viewport: ViewportSize,
) -> None:
    site = repository_root / "site"
    if not (site / "index.html").is_file():
        pytest.skip("build the MkDocs site before browser tests")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page, network_routes = _new_page(browser, site, viewport)
        routes = _all_navigation_routes(repository_root)
        assert set(_IMPORTANT_ROUTES).issubset(routes)
        for route in routes:
            _assert_local_page(
                page,
                _site_file(site, route),
                _site_url(route),
                network_routes,
            )
            failures = _audit_page(page, require_playground=route == "playground.md")
            assert failures == [], f"{route}: {failures}"
            violations = _serious_axe_violations(page)
            assert violations == [], f"{route}:\n" + "\n".join(violations)
        browser.close()


def test_keyboard_navigation_search_and_static_playground(repository_root: Path) -> None:
    site = repository_root / "site"
    if not (site / "index.html").is_file():
        pytest.skip("build the MkDocs site before browser tests")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page, network_routes = _new_page(browser, site, {"width": 1280, "height": 800})

        _assert_local_page(
            page,
            _site_file(site, "index.md"),
            _site_url("index.md"),
            network_routes,
        )
        search = page.locator("[data-md-component='search-query']")
        search.fill("Custom Structured Output")
        result = page.locator(".md-search-result__link").filter(has_text="Custom Structured Output")
        result.first.wait_for(state="visible")
        result.first.focus()
        assert result.first.evaluate("element => element === document.activeElement")
        page.keyboard.press("Enter")
        page.wait_for_load_state("load")
        assert page.locator("h1").inner_text().startswith("Custom Structured Output")

        _assert_local_page(
            page,
            _site_file(site, "playground.md"),
            _site_url("playground.md"),
            network_routes,
        )
        selected = page.locator("[role='tab'][aria-selected='true']")
        assert selected.inner_text() == "Success"
        selected.focus()
        page.keyboard.press("ArrowRight")
        assert page.locator("[role='tab'][aria-selected='true']").inner_text() == "Partial"
        assert page.locator("[data-status]").inner_text().lower() == "partial"
        assert page.locator("[data-default-exit]").inner_text() == "0"
        assert page.locator("[data-strict-exit]").inner_text() == "1"
        page.keyboard.press("End")
        assert page.locator("[role='tab'][aria-selected='true']").inner_text() == "Failed"
        assert page.locator("[data-status]").inner_text().lower() == "failed"
        page.keyboard.press("Home")
        assert page.locator("[role='tab'][aria-selected='true']").inner_text() == "Success"
        storage = page.evaluate(
            "({local: Object.keys(localStorage), session: Object.keys(sessionStorage), "
            "cookie: document.cookie})"
        )
        assert storage == {"local": [], "session": [], "cookie": ""}
        assert (
            page.evaluate(
                "navigator.serviceWorker ? navigator.serviceWorker.getRegistrations()"
                ".then(items => items.length) : 0"
            )
            == 0
        )
        assert network_routes == []
        browser.close()
