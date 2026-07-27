"""
Image Agent
=======================
Extracts every embedded picture/figure/chart from a DoclingDocument and
saves it to disk. Deterministic -- no LLM call, no API key needed.

Docling already renders each PictureItem's image in memory (as a PNG,
via ImageRef) when the converter is run with
generate_picture_images=True (see extractors/docling_convert.py). This
agent's job is purely to walk doc.pictures, save each rendered image to
`output_dir`, and record its page/format/path/caption -- a mechanical
extraction task, not a reasoning task.

Consumed by the eventual document-metadata orchestrator, which merges
this agent's output with the text/language/table agents' output into
one JSON file.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docling_core.types.doc.document import DoclingDocument

from schemas.image_structure import DocumentImageStructure, ImageBlock


def extract_images(
    doc: DoclingDocument,
    source_file: str,
    output_dir: Path,
) -> DocumentImageStructure:
    """
    Walks a DoclingDocument's pictures and saves each renderable one to
    `output_dir/images/{source_stem}_img{image_id}.png`.

    Images Docling could not render (item.image is None -- e.g. the
    converter ran with generate_picture_images=False, or rendering that
    particular image failed) are still recorded with format="unknown"
    and file_path=None, so the page/caption metadata isn't silently
    dropped even when the pixel data is unavailable.
    """
    source_stem = Path(source_file).stem
    images_dir = output_dir / "images"

    blocks: list[ImageBlock] = []
    for image_id, item in enumerate(doc.pictures):
        page = item.prov[0].page_no if item.prov else 0
        caption = item.caption_text(doc).strip() or None

        if item.image is None:
            blocks.append(ImageBlock(
                image_id=image_id,
                page=page,
                format="unknown",
                file_path=None,
                caption=caption,
            ))
            continue

        pil_image = item.image.pil_image
        if pil_image is None:
            blocks.append(ImageBlock(
                image_id=image_id,
                page=page,
                format=item.image.mimetype,
                file_path=None,
                caption=caption,
            ))
            continue

        images_dir.mkdir(parents=True, exist_ok=True)
        file_path = images_dir / f"{source_stem}_img{image_id}.png"
        pil_image.save(file_path, format="PNG")

        blocks.append(ImageBlock(
            image_id=image_id,
            page=page,
            format=item.image.mimetype,
            file_path=str(file_path.relative_to(output_dir)),
            width=pil_image.width,
            height=pil_image.height,
            caption=caption,
        ))

    return DocumentImageStructure(
        source_file=Path(source_file).name,
        page_count=len(doc.pages),
        images=blocks,
        extraction_date=date.today(),
    )
