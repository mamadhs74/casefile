"""Text extraction from fetched content: HTML via trafilatura, PDF via pypdf.

Archival court records and inquest reports are very often scans with no
text layer -- extraction on those returns empty or near-empty text,
silently, on exactly the highest-value Tier A documents. OCR is out of
scope (see docs/SCHEMA.md's known gaps); the failure this module produces
instead is legible: EmptyExtractionError names the likely cause rather than
letting a content-free Source row that could never support a claim get
persisted.

Word count alone is not a specificity check -- see docs/SCHEMA.md's
"Extraction specificity" section for the full investigation. Two things
from that investigation land here:

- `favor_precision=True` on the HTML path. Empirically, this turns
  trafilatura's nav/boilerplate fallback (which otherwise returns
  plausible-length text scraped from <nav>/<header>/<footer> when it can't
  confidently identify real article content) into an empty result, at no
  observed cost to genuine content, including short ones -- a one-
  paragraph court order kept all of its substance under this setting.
- MIN_EXTRACTED_WORD_COUNT raised from 25 to 40, high enough to reject
  most no-teaser paywall stubs outright, deliberately not raised further:
  the binding constraint is a real short primary record (the same court-
  order fixture, 30-34 words), and a floor tuned to also catch heavier
  boilerplate would reject exactly that kind of terse, legitimate Tier A
  document. Structural detection of *that* failure mode (a generic-but-
  well-formed page, not a link-heavy fallback) is handled separately by
  packages/research/boilerplate.py's domain-reference-sample check, not by
  this floor -- word count was never going to be able to do both jobs.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime

import pypdf
import trafilatura

MIN_EXTRACTED_WORD_COUNT = 40


@dataclass(frozen=True)
class ExtractedContent:
    text: str
    word_count: int
    title: str | None
    publisher: str | None
    published_date: date | None


class EmptyExtractionError(Exception):
    """Extraction produced no usable text. For a PDF, this is very often a
    scan with no text layer -- OCR is out of scope, see docs/SCHEMA.md's
    known gaps -- but it's also what a corrupted or encrypted PDF produces,
    so the message hedges rather than overclaiming a specific cause."""

    def __init__(self, url: str, is_pdf: bool, word_count: int) -> None:
        self.url = url
        self.is_pdf = is_pdf
        self.word_count = word_count
        cause = (
            "probable scan with no text layer (or an unreadable/encrypted "
            "PDF) -- OCR is out of scope"
            if is_pdf
            else "page returned no extractable article content"
        )
        super().__init__(
            f"{url!r} produced only {word_count} word(s) of extracted text ({cause})"
        )


def sniff_is_pdf(content: bytes, declared_content_type: str) -> bool:
    if "pdf" in declared_content_type.lower():
        return True
    return content[:5] == b"%PDF-"


def extract(url: str, content: bytes, declared_content_type: str) -> ExtractedContent:
    """Raises EmptyExtractionError if the result is below
    MIN_EXTRACTED_WORD_COUNT -- callers must not persist a Source from a
    result that fails this, see packages/research/fetch.py."""
    is_pdf = sniff_is_pdf(content, declared_content_type)
    text, title, publisher, published_date = (
        _extract_pdf(content) if is_pdf else _extract_html(url, content)
    )

    word_count = len(text.split())
    if word_count < MIN_EXTRACTED_WORD_COUNT:
        raise EmptyExtractionError(url, is_pdf, word_count)

    return ExtractedContent(
        text=text,
        word_count=word_count,
        title=title,
        publisher=publisher,
        published_date=published_date,
    )


def _extract_html(url: str, content: bytes) -> tuple[str, str | None, str | None, date | None]:
    html = content.decode("utf-8", errors="replace")
    # favor_precision=True -- see module docstring. Biases trafilatura
    # against returning content it isn't confident about, which is exactly
    # the nav/header/footer fallback text this needs to not treat as an
    # article.
    text = trafilatura.extract(html, url=url, favor_precision=True) or ""
    meta = trafilatura.extract_metadata(html, default_url=url)

    title = meta.title if meta is not None else None
    publisher = meta.sitename if meta is not None else None
    published_date = None
    if meta is not None and meta.date:
        try:
            published_date = datetime.strptime(meta.date, "%Y-%m-%d").date()
        except ValueError:
            published_date = None

    return text, title, publisher, published_date


def _extract_pdf(content: bytes) -> tuple[str, str | None, str | None, date | None]:
    # PDF metadata (title/author) is frequently absent or garbage for
    # scanned court/inquest documents -- best-effort only, and any failure
    # to even open the file (corrupted, encrypted) falls through to an
    # empty result rather than raising here, so it hits the same
    # EmptyExtractionError as a no-text-layer scan.
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
        title = None
        if reader.metadata is not None and reader.metadata.title:
            title = reader.metadata.title.strip() or None
    except Exception:
        text = ""
        title = None

    return text, title, None, None
