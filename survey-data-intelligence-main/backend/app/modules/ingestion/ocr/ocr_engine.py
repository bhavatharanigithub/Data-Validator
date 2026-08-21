"""Local, CPU-only OCR extraction via PaddleOCR.

Keeps the existing, working PaddleOCR initialization untouched (CPU device,
orientation/unwarping classifiers disabled). PDFs are rasterized page by
page with PyMuPDF -- a pure-wheel dependency that needs no system binaries
(unlike poppler/pdf2image), which matters on the target Windows/no-Docker
environment.

This module is the only place that imports paddleocr/fitz, so the rest of
the OCR feature (parser, normalizer, router) can be exercised and unit
tested without either dependency installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.modules.ingestion.ocr.constants import MAX_PDF_PAGES
from app.modules.ingestion.ocr.parser import OcrLine

logger = logging.getLogger("survey_validator.ingestion.ocr")

_PDF_RENDER_DPI = 200

_engine = None
_engine_lock = Lock()


class OcrEngineError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _get_engine():
    """Lazily create a single shared PaddleOCR instance.

    Loading the model is expensive; every preview request reuses the same
    instance rather than re-initializing PaddleOCR per upload.
    """
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise OcrEngineError(
                "PaddleOCR is not installed in this environment."
            ) from exc
        try:
            _engine = PaddleOCR(
                lang="en",
                device="cpu",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except Exception as exc:  # pragma: no cover - environment-dependent
            logger.exception("OCR_ENGINE_INIT_FAILED")
            raise OcrEngineError("OCR engine failed to initialize.") from exc
    return _engine


@dataclass
class PageOcrResult:
    page: int
    lines: list[OcrLine]


def _predict_single(image_path: Path, page: int) -> PageOcrResult:
    engine = _get_engine()
    try:
        results = engine.predict(str(image_path))
    except Exception as exc:  # pragma: no cover - environment-dependent
        logger.exception("OCR_PREDICT_FAILED", extra={"page": page})
        raise OcrEngineError(f"OCR failed on page {page}.") from exc

    lines: list[OcrLine] = []
    for result in results or []:
        # PaddleOCR 3.x pipeline results behave like a dict with rec_texts /
        # rec_scores (and rec_boxes, unused for parsing but kept available
        # for future confidence-by-position work).
        texts = result.get("rec_texts") or []
        scores = result.get("rec_scores") or []
        for idx, text in enumerate(texts):
            if not str(text).strip():
                continue
            score = float(scores[idx]) if idx < len(scores) and scores[idx] is not None else None
            lines.append(OcrLine(text=str(text), score=score, page=page))
    return PageOcrResult(page=page, lines=lines)


def extract_from_image(image_path: Path) -> list[PageOcrResult]:
    return [_predict_single(image_path, page=1)]


def extract_from_pdf(pdf_path: Path, tmp_dir: Path) -> list[PageOcrResult]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise OcrEngineError("PDF support (PyMuPDF) is not installed in this environment.") from exc

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise OcrEngineError("The PDF could not be opened. It may be corrupted.") from exc

    if doc.page_count == 0:
        doc.close()
        raise OcrEngineError("The PDF has no pages.")
    if doc.page_count > MAX_PDF_PAGES:
        doc.close()
        raise OcrEngineError(
            f"The PDF has {doc.page_count} pages, which exceeds the {MAX_PDF_PAGES}-page limit."
        )

    zoom = _PDF_RENDER_DPI / 72
    matrix = fitz.Matrix(zoom, zoom)
    pages: list[PageOcrResult] = []
    try:
        for index in range(doc.page_count):
            page = doc.load_page(index)
            pixmap = page.get_pixmap(matrix=matrix)
            page_image_path = tmp_dir / f"page_{index + 1}.png"
            pixmap.save(str(page_image_path))
            page_result = _predict_single(page_image_path, page=index + 1)
            pages.append(page_result)
    finally:
        doc.close()
    return pages
