# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "anthropic==0.64.0",
#   "docling==2.54.0",
#   "easyocr==1.7.2",
#   "instructor==1.10.0",
#   "lingua-language-detector==2.1.1",
#   "loguru==0.7.3",
#   "openai==1.99.9",
#   "openpyxl==3.1.5",
#   "pydantic==2.11.7",
#   "pymupdf==1.26.4",
#   "tenacity==9.1.2",
#   "tiktoken==0.11.0",
# ]
# ///
"""Probe selected dependency imports without credentials or model downloads."""

from __future__ import annotations

import platform
import sys
from importlib.metadata import version

from loguru import logger

EXPECTED = {
    "anthropic": "0.64.0",
    "docling": "2.54.0",
    "easyocr": "1.7.2",
    "instructor": "1.10.0",
    "lingua-language-detector": "2.1.1",
    "loguru": "0.7.3",
    "openai": "1.99.9",
    "openpyxl": "3.1.5",
    "pydantic": "2.11.7",
    "pymupdf": "1.26.4",
    "tenacity": "9.1.2",
    "tiktoken": "0.11.0",
}


def probe() -> None:
    """Import the exact APIs required by the package architecture."""
    from anthropic import Anthropic, AsyncAnthropic
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter
    from easyocr import Reader
    from fitz import Document as FitzDocument
    from instructor import from_anthropic, from_openai
    from lingua import LanguageDetectorBuilder
    from openai import AsyncAzureOpenAI, AsyncOpenAI, AzureOpenAI, OpenAI
    from openpyxl import load_workbook
    from pydantic import BaseModel
    from pymupdf import Document as PyMuPDFDocument
    from tenacity import retry
    from tiktoken import encoding_for_model

    required = (
        Anthropic,
        AsyncAnthropic,
        Reader,
        FitzDocument,
        PyPdfiumDocumentBackend,
        EasyOcrOptions,
        PdfPipelineOptions,
        DocumentConverter,
        from_anthropic,
        from_openai,
        LanguageDetectorBuilder,
        AsyncAzureOpenAI,
        AsyncOpenAI,
        AzureOpenAI,
        OpenAI,
        load_workbook,
        BaseModel,
        PyMuPDFDocument,
        retry,
        encoding_for_model,
    )
    if any(item is None for item in required):
        raise RuntimeError("A required dependency API resolved to None")

    mismatches = {
        package: (expected, version(package))
        for package, expected in EXPECTED.items()
        if version(package) != expected
    }
    if mismatches:
        raise RuntimeError(f"Version mismatch: {mismatches}")


def main() -> int:
    """Run the compatibility probe and return a process status."""
    logger.remove()
    logger.add(sys.stderr, format="{message}")
    try:
        probe()
    except Exception:
        logger.exception("Dependency probe failed")
        return 1

    logger.info(
        "Dependency probe passed: Python {} on {} {}",
        platform.python_version(),
        platform.system(),
        platform.machine(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
