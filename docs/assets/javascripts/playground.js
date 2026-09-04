(function () {
  "use strict";

  function initialize(root) {
    if (root.dataset.initialized === "true") {
      return;
    }
    const dataElement = document.getElementById("playground-data");
    if (!dataElement) {
      return;
    }
    const samples = JSON.parse(dataElement.textContent);
    const tabs = Array.from(root.querySelectorAll("[role='tab']"));
    const panel = root.querySelector("[role='tabpanel']");
    const status = root.querySelector("[data-status]");
    const variables = root.querySelector("[data-variables]");
    const diagnostics = root.querySelector("[data-diagnostics]");
    const resultJson = root.querySelector("[data-result-json]");

    function setText(selector, value) {
      const target = root.querySelector(selector);
      if (target) {
        target.textContent = String(value);
      }
    }

    function render(sampleName, focus) {
      const sample = samples[sampleName];
      const activeTab = tabs.find((tab) => tab.dataset.sample === sampleName);
      if (!sample || !activeTab || !panel || !status || !variables || !diagnostics || !resultJson) {
        return;
      }
      tabs.forEach((tab) => {
        const selected = tab === activeTab;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
      });
      panel.setAttribute("aria-labelledby", activeTab.id);
      status.className = `status-chip status-chip--${sample.status}`;
      status.textContent = sample.status;
      setText("[data-variable-count]", sample.result.variables.length);
      setText("[data-diagnostic-count]", sample.result.diagnostics.length);
      setText("[data-failed-count]", sample.result.failed_blocks.length);
      setText("[data-default-exit]", sample.default_exit);
      setText("[data-strict-exit]", sample.strict_exit);

      variables.replaceChildren();
      if (sample.result.variables.length === 0) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 3;
        cell.textContent = "No usable variables";
        row.append(cell);
        variables.append(row);
      } else {
        sample.result.variables.forEach((variable) => {
          const row = document.createElement("tr");
          [variable.raw_name, variable.data_type, variable.needs_review ? "Yes" : "No"].forEach(
            (value) => {
              const cell = document.createElement("td");
              cell.textContent = value;
              row.append(cell);
            }
          );
          variables.append(row);
        });
      }

      diagnostics.replaceChildren();
      if (sample.result.diagnostics.length === 0) {
        const item = document.createElement("li");
        item.textContent = "No diagnostics";
        diagnostics.append(item);
      } else {
        sample.result.diagnostics.forEach((diagnostic) => {
          const item = document.createElement("li");
          item.textContent = `${diagnostic.code} (${diagnostic.severity})`;
          diagnostics.append(item);
        });
      }
      resultJson.textContent = JSON.stringify(sample.result, null, 2);
      if (focus) {
        activeTab.focus();
      }
    }

    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => render(tab.dataset.sample, false));
      tab.addEventListener("keydown", (event) => {
        let next = index;
        if (event.key === "ArrowRight") {
          next = (index + 1) % tabs.length;
        } else if (event.key === "ArrowLeft") {
          next = (index - 1 + tabs.length) % tabs.length;
        } else if (event.key === "Home") {
          next = 0;
        } else if (event.key === "End") {
          next = tabs.length - 1;
        } else {
          return;
        }
        event.preventDefault();
        render(tabs[next].dataset.sample, true);
      });
    });
    root.dataset.initialized = "true";
    render("success", false);
  }

  function initializeAll() {
    document.querySelectorAll("[data-static-playground]").forEach(initialize);
    document.querySelectorAll("[role='progressbar']:not([aria-label])").forEach((progress) => {
      progress.setAttribute("aria-label", "Page loading progress");
    });
    document
      .querySelectorAll(".md-typeset__scrollwrap:not([tabindex]), .tabbed-labels:not([tabindex])")
      .forEach((region) => {
        region.tabIndex = 0;
        region.setAttribute(
          "aria-label",
          region.classList.contains("tabbed-labels") ? "Scrollable tabs" : "Scrollable table"
        );
      });
  }

  document.addEventListener("DOMContentLoaded", initializeAll);
  if (typeof document$ !== "undefined") {
    document$.subscribe(initializeAll);
  }
})();
