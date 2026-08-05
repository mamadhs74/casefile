"""Shared verbatim-span location.

Not duplicated between packages/research/claim_extraction.py (ClaimSource's
quoted_span) and packages/db/listeners.py (Entity.living_evidence, the R8
evidence invariant) -- both need exactly the same notion of "this quote is
really in this text," and drift between two independent implementations
would be a real bug, not a style nit: the whole point of a located span is
that it's verifiable, and a mismatched matching rule between the two callers
would make that guarantee mean something different depending on which one
you're reading. Mirrors packages/domain/urls.py::derive_domain()'s own
reasoning for moving out of packages/db/listeners.py -- same shape of
problem, one layer over.
"""

from __future__ import annotations

import re


def locate_span(quote: str, source_text: str) -> tuple[int, int] | None:
    """Find quote in source_text allowing only whitespace differences.
    Every non-whitespace character in quote must appear literally, in
    order; any run of whitespace in quote matches any run of whitespace in
    the source (a single PDF line-wrap, several blank-line page-break
    newlines, whatever). Built as a regex from quote's own whitespace-
    delimited tokens, escaped, joined by \\s+, and searched directly
    against the original text -- so the real (start, end) comes straight
    from the match, with no separate normalized copy to remap offsets out
    of. Returns None if no such match exists anywhere in the source."""
    tokens = quote.split()
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(pattern, source_text)
    if match is None:
        return None
    return match.start(), match.end()
