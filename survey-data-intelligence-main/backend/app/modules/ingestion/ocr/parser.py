"""Turn raw OCR line output into raw (unnormalized) survey record blocks.

The parser is intentionally tolerant of the ways PaddleOCR can fragment a
printed/handwritten survey form: a label and its value can be on the same
line ("District: Chennai"), on separate lines ("District" / "Chennai"), or
separated by a bare colon line produced by OCR ("Income" / ":" / "25000").

This module has no dependency on PaddleOCR itself -- it only consumes
plain ``OcrLine`` records (text + recognition score + page number), which
keeps it trivially unit-testable without a working OCR install.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.modules.ingestion.ocr.constants import FIELD_ALIASES

_BARE_SEPARATOR_RE = re.compile(r"^[:\uFF1A\-–—]\s*$")
_LEADING_SEPARATOR_RE = re.compile(r"^[:\uFF1A]\s*")
_TRAILING_SEPARATOR_RE = re.compile(r"[:\uFF1A]\s*$")

# Build one alias -> compiled regex per field, longest alias first so
# "marital status" is tried before a hypothetical shorter overlapping alias.
_LABEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = []
for _field, _aliases in FIELD_ALIASES:
    for _alias in sorted(_aliases, key=len, reverse=True):
        pattern = re.compile(
            rf"^\s*{re.escape(_alias)}\s*[:\uFF1A]?\s*(.*)$", re.IGNORECASE
        )
        _LABEL_PATTERNS.append((_field, pattern))


@dataclass(frozen=True)
class OcrLine:
    text: str
    score: float | None
    page: int


@dataclass
class RawFieldValue:
    value: str | None
    score: float | None


@dataclass
class RawRecord:
    page: int
    fields: dict[str, RawFieldValue] = field(default_factory=dict)


def _match_label(text: str) -> tuple[str | None, str]:
    """Return (canonical_field, inline_value) if the line is a known label."""
    stripped = text.strip()
    if not stripped:
        return None, ""
    for canonical_field, pattern in _LABEL_PATTERNS:
        m = pattern.match(stripped)
        if m:
            return canonical_field, m.group(1).strip()
    return None, ""


def _is_bare_separator(text: str) -> bool:
    return bool(_BARE_SEPARATOR_RE.match(text.strip()))


def _clean_inline_value(value: str) -> str:
    value = _LEADING_SEPARATOR_RE.sub("", value)
    value = _TRAILING_SEPARATOR_RE.sub("", value)
    return value.strip()


def _average_score(lines: list[OcrLine]) -> float | None:
    scores = [ln.score for ln in lines if ln.score is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _parse_block(lines: list[OcrLine], page: int) -> RawRecord:
    record = RawRecord(page=page)
    i = 0
    n = len(lines)
    while i < n:
        canonical_field, inline_value = _match_label(lines[i].text)
        if canonical_field is None:
            i += 1
            continue

        contributing = [lines[i]]
        value = _clean_inline_value(inline_value)
        j = i + 1

        if not value:
            # Skip any bare separator lines OCR emitted on their own line.
            while j < n and _is_bare_separator(lines[j].text):
                contributing.append(lines[j])
                j += 1
            if j < n:
                next_field, _ = _match_label(lines[j].text)
                if next_field is None:
                    candidate = _clean_inline_value(lines[j].text.strip())
                    if candidate:
                        value = candidate
                        contributing.append(lines[j])
                        j += 1

        # First occurrence of a field wins within a block; a later repeat is
        # ignored rather than silently overwriting an already-parsed value.
        if canonical_field not in record.fields or not record.fields[canonical_field].value:
            record.fields[canonical_field] = RawFieldValue(
                value=value or None, score=_average_score(contributing)
            )

        i = j if j > i + 1 else i + 1

    return record


def parse_ocr_lines(lines: list[OcrLine]) -> list[RawRecord]:
    """Split OCR lines into per-record blocks and parse each block.

    A new record starts at every line that resolves to the ``record_id``
    field. Lines before the first record marker (form titles, instructions)
    and trailing lines that don't match any known field (signature blocks,
    surveyor name) are naturally ignored.
    """
    start_indices = [
        idx for idx, ln in enumerate(lines) if _match_label(ln.text)[0] == "record_id"
    ]
    if not start_indices:
        return []

    records: list[RawRecord] = []
    for pos, start in enumerate(start_indices):
        end = start_indices[pos + 1] if pos + 1 < len(start_indices) else len(lines)
        block = lines[start:end]
        records.append(_parse_block(block, page=block[0].page if block else 1))
    return records
