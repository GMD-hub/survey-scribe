"""
Tests for the Image Agent (agents/image_agent.py).

Builds a small DoclingDocument programmatically (no PDF/Docling
conversion involved) so these tests are fast and exercise only the
image-saving + metadata logic in extract_images().
"""
from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image as PILImage

from docling_core.types.doc import (
    BoundingBox,
    DoclingDocument,
    ImageRef,
    ProvenanceItem,
    Size,
)

from agents.image_agent import extract_images


def _image_ref(width: int = 4, height: int = 4) -> ImageRef:
    """Builds a real (tiny) in-memory PNG wrapped in an ImageRef, the
    same shape Docling produces when generate_picture_images=True."""
    pil_image = PILImage.new("RGB", (width, height), color="white")
    buffer = BytesIO()
    pil_image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return ImageRef(
        mimetype="image/png",
        dpi=72,
        size=Size(width=width, height=height),
        uri=f"data:image/png;base64,{encoded}",
    )


def _prov(page_no: int) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=0, t=0, r=10, b=10),
        charspan=(0, 0),
    )


def _sample_doc() -> DoclingDocument:
    doc = DoclingDocument(name="sample")
    doc.add_picture(image=_image_ref(), prov=_prov(page_no=1))
    doc.add_picture(image=_image_ref(width=8, height=6), prov=_prov(page_no=3))
    doc.add_picture(image=None, prov=_prov(page_no=5))  # unrendered picture
    return doc


def test_extracts_one_block_per_picture(tmp_path):
    doc = _sample_doc()
    structure = extract_images(doc, source_file="sample.pdf", output_dir=tmp_path)
    assert len(structure.images) == 3


def test_rendered_image_gets_saved_with_correct_page_and_format(tmp_path):
    doc = _sample_doc()
    structure = extract_images(doc, source_file="sample.pdf", output_dir=tmp_path)

    first = structure.images[0]
    assert first.page == 1
    assert first.format == "image/png"
    assert first.file_path is not None
    assert (tmp_path / first.file_path).exists()


def test_saved_image_dimensions_match_source(tmp_path):
    doc = _sample_doc()
    structure = extract_images(doc, source_file="sample.pdf", output_dir=tmp_path)

    second = structure.images[1]
    assert second.width == 8
    assert second.height == 6


def test_unrendered_picture_is_recorded_without_file_path(tmp_path):
    doc = _sample_doc()
    structure = extract_images(doc, source_file="sample.pdf", output_dir=tmp_path)

    third = structure.images[2]
    assert third.page == 5
    assert third.format == "unknown"
    assert third.file_path is None


def test_image_ids_follow_reading_order(tmp_path):
    doc = _sample_doc()
    structure = extract_images(doc, source_file="sample.pdf", output_dir=tmp_path)
    assert [img.image_id for img in structure.images] == [0, 1, 2]


def test_source_file_and_page_count_are_recorded(tmp_path):
    doc = _sample_doc()
    structure = extract_images(doc, source_file="sample.pdf", output_dir=tmp_path)
    assert structure.source_file == "sample.pdf"
    assert structure.page_count == len(doc.pages)
