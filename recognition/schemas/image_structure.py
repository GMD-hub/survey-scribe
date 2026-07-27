"""
Image Structure Schema
=========================
Pydantic models for the output of the Image Agent
(agents/image_agent.py).

Separate from schemas/text_structure.py: this describes embedded
pictures/figures/charts in the PDF (page, format, saved file path), not
text content or heading hierarchy.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class ImageBlock(BaseModel):
    """One embedded picture/figure/chart -- one Docling PictureItem."""

    image_id: int
    # Stable position of this image within the document's reading order.
    # Also used as part of the saved file's name.

    page: int
    # 1-indexed PDF page number this image appears on.
    # 0 if Docling could not determine provenance for this image.

    format: str
    # Image MIME type, e.g. "image/png". "unknown" if Docling could not
    # render this image (file_path will be None in that case).

    file_path: Optional[str] = None
    # Path of the saved image file, relative to the output directory
    # passed to extract_images(). None if the image could not be
    # rendered/saved.

    width: Optional[int] = None
    height: Optional[int] = None
    # Pixel dimensions of the saved image, if available.

    caption: Optional[str] = None
    # Caption text associated with this image, if Docling detected one.
    # None if there is no caption.


class DocumentImageStructure(BaseModel):
    """
    Full image-structure extraction result for one PDF.
    Written as JSON by recognition/pipeline.py.
    """

    source_file: str
    # Filename of the source PDF (not the full path).

    page_count: int
    # Total number of pages Docling parsed.

    images: list[ImageBlock]
    # All embedded pictures/figures/charts, in reading order.

    extraction_date: date

    extraction_notes: Optional[str] = None
    # Free-text notes, e.g. if an image failed to render or save.
