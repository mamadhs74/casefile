"""packages/research/extraction.py: HTML via trafilatura, PDF via pypdf, and
the empty-extraction rejection that exists specifically because archival
court records and inquest reports are very often scans with no text layer.
"""

from __future__ import annotations

import pytest

from packages.research.extraction import EmptyExtractionError, extract, sniff_is_pdf

ARTICLE_HTML = b"""
<html>
<head><title>Six Vanish From Bavarian Farmstead</title></head>
<body>
<article>
<p>In March 1922, six people vanished from a small farmstead in Bavaria.
Andreas Gruber, his wife, their widowed daughter, and her four children had
not been seen for several days when a neighbor grew concerned and went to
check on them. Investigators later determined the family had been killed.</p>
</article>
</body>
</html>
"""

THIN_HTML = b"<html><head><title>x</title></head><body><p>Too short.</p></body></html>"

# A minimal, valid, single-page PDF with a real text-drawing content stream --
# see the exploration in this session for how this was verified to work with
# pypdf despite the informal xref table (pypdf's fallback parser recovers).
_PDF_WITH_TEXT_STREAM = (
    b"BT /F1 24 Tf 72 700 Td (This is a real extracted test sentence with "
    b"enough words in it to comfortably clear the minimum extracted word "
    b"count threshold this module enforces before persisting anything "
    b"resembling a Source record for real archival material such as an "
    b"inquest report or a court filing scanned with an intact text layer.) Tj ET"
)
PDF_WITH_TEXT = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
    b"/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n"
    b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"5 0 obj\n<< /Length " + str(len(_PDF_WITH_TEXT_STREAM)).encode() + b" >>\nstream\n"
    + _PDF_WITH_TEXT_STREAM + b"\nendstream\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF"
)

# Same structure, empty content stream -- models a scanned page with no text layer.
PDF_SCAN_NO_TEXT_LAYER = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << >> "
    b"/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n"
    b"5 0 obj\n<< /Length 0 >>\nstream\n\nendstream\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF"
)


def test_html_extraction_returns_text_and_metadata() -> None:
    result = extract("https://example.com/article", ARTICLE_HTML, "text/html")

    assert "Andreas Gruber" in result.text
    assert result.word_count > 25
    assert result.title == "Six Vanish From Bavarian Farmstead"


def test_html_with_too_little_content_raises_empty_extraction_error() -> None:
    with pytest.raises(EmptyExtractionError) as exc_info:
        extract("https://example.com/thin", THIN_HTML, "text/html")

    assert exc_info.value.is_pdf is False


def test_pdf_with_text_layer_extracts() -> None:
    result = extract("https://example.gov/filing.pdf", PDF_WITH_TEXT, "application/pdf")

    assert "real extracted test sentence" in result.text
    assert result.word_count > 0


def test_pdf_scan_with_no_text_layer_raises_empty_extraction_error() -> None:
    """The exact failure mode this rule exists for: a court-record scan
    with no text layer must fail loudly, not persist as a content-free
    Source that can never support a claim."""
    with pytest.raises(EmptyExtractionError) as exc_info:
        extract("https://example.gov/scan.pdf", PDF_SCAN_NO_TEXT_LAYER, "application/pdf")

    assert exc_info.value.is_pdf is True
    assert "scan" in str(exc_info.value).lower()


def test_sniff_is_pdf_by_content_type() -> None:
    assert sniff_is_pdf(b"whatever", "application/pdf") is True
    assert sniff_is_pdf(b"whatever", "application/pdf; charset=binary") is True


def test_sniff_is_pdf_by_magic_bytes_when_content_type_is_generic() -> None:
    assert sniff_is_pdf(PDF_WITH_TEXT, "application/octet-stream") is True
    assert sniff_is_pdf(ARTICLE_HTML, "application/octet-stream") is False
