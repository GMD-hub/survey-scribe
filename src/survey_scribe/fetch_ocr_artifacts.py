"""Docker build-time fetch and checksum verification of approved OCR archives.

Also fetches Docling's layout and TableFormer models via Docling's own
offline model downloader, since ``pipeline_options.artifacts_path`` in
``sources/docling.py`` is a single shared root Docling uses to locate every
model family (not just EasyOCR, which is separately pinned/verified below and
loaded through ``EasyOcrOptions.model_storage_directory`` instead). Questionnaires
routed through this pipeline rely heavily on table-structure detection.

Run from the ``ocr-artifacts`` Dockerfile stage only; not part of the package.
"""

import urllib.request
import zipfile
from pathlib import Path

from docling.utils.model_downloader import download_models

from ocr import APPROVED_OCR_ARTIFACTS, resolve_ocr_cache

_RELEASE_URLS = {
    "craft_mlt_25k.zip": (
        "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip"
    ),
    "english_g2.zip": "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip",
}


def main() -> None:
    cache = Path("/ocr/cache")
    cache.mkdir(parents=True, exist_ok=True)

    for artifact in APPROVED_OCR_ARTIFACTS:
        archive = cache / artifact.filename
        urllib.request.urlretrieve(_RELEASE_URLS[artifact.filename], archive)
        model_name = f"{Path(artifact.filename).stem}.pth"
        with zipfile.ZipFile(archive) as bundle:
            member = next(
                item
                for item in bundle.infolist()
                if not item.is_dir() and Path(item.filename).name == model_name
            )
            (cache / model_name).write_bytes(bundle.read(member))

    # Fails the build if any fetched archive or extracted model does not
    # match the approved size/SHA-256 manifest.
    resolve_ocr_cache(cache)

    # Layout and TableFormer only; EasyOCR is already pinned/verified above.
    # with_rapidocr defaults to True upstream and would pull in an OpenCV
    # (cv2) dependency this build stage doesn't have native libs for.
    download_models(
        output_dir=cache,
        with_layout=True,
        with_tableformer=True,
        with_rapidocr=False,
        with_easyocr=False,
    )


if __name__ == "__main__":
    main()

