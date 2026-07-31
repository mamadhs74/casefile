"""License resolution per docs/ARCHIVE-SPEC.md.

An unparseable license is a rejection, not a warning. `resolve()` returns
`None` for anything it cannot positively identify -- callers must drop the
candidate rather than guess. Match order, most specific first:

1. A recognized license URL (creativecommons.org, rightsstatements.org). Once
   the host is recognized, an unmatched path is a license we decline, not an
   unknown authority -- it does not fall through to raw_rights.
2. A known Wikimedia-style template string, or a structurally parsed
   Creative Commons attribution-family reference (see
   _parse_cc_attribution_family).
3. A provider-wide default, only for catalogs that guarantee one uniform
   license (Pexels, Pixabay).
4. Otherwise None.

Grow tests/fixtures/rights_strings.json every time this rejects something it
shouldn't -- that file is the actual asset; this module is a function over it.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from packages.domain.enums import LicenseType

# Wikimedia (and Europeana, which reuses CC's short names) express the same
# license under many spellings: "CC0", "CC0 1.0", "cc-by-sa-4.0", "Attribution
# 4.0 International". Normalizing to lowercase words-and-dots collapses that
# variation onto a small, exact-match vocabulary instead of a guessing regex.
#
# Every entry here must be a fixed point of _normalize -- i.e. _normalize(x)
# == x -- or it can never match anything, since _from_template always
# normalizes the input before comparing. tests/test_licensing.py asserts this
# for the whole set so a typo here fails loudly instead of just never firing.
_CC0_TEMPLATES = frozenset(
    {
        "cc0",
        "cc0 1.0",
        "cc0 1.0 universal",
        "public domain dedication",
        "creative commons cc0 1.0 universal public domain dedication",
    }
)

_PUBLIC_DOMAIN_TEMPLATES = frozenset(
    {
        "public domain",
        "public domain mark",
        "pd",
        "pd old",
        "pd old 70",
        "pd old 75",
        "pd old 80",
        "pd old 100",
        "pd us",
        "pd us expired",
        "pd usgov",
        "pd usgov military",
        "pd usgov edict",
        "pd government",
        "pd self",
        # Deliberately NOT here: "pd art" (and its old-70/old-100 variants)
        # and "pd scan". PD-Art's premise -- that a faithful photographic
        # reproduction of a 2D public-domain artwork carries no new copyright
        # -- does not hold under German law (BGH 2018, Reiss-Engelhorn-
        # Museen), and that risk lives in the reproduction, not the
        # underlying artwork's age, so combining it with an old-70/old-100
        # claim doesn't rescue it. PD-scan has the same shape: the claim
        # covers the scan process, never the underlying work. Both surface
        # for manual review instead of resolving silently.
    }
)

# Creative Commons attribution-family naming is systematic: an optional
# "cc" or "creative commons" prefix, then one or more elements, then a
# version, then an optional jurisdiction port. Parsing that structure
# instead of enumerating strings is what lets "CC BY-SA 3.0 DE" and
# "CC BY 1.0" and "Creative Commons Attribution-ShareAlike 4.0
# International" (the long form Wikimedia extmetadata's UsageTerms field
# actually uses) all resolve without naming each one -- jurisdiction ports
# in particular are common on German Wikimedia material and there are
# dozens.
#
# Short codes and their long-form spellings both map to the same element.
# "sharealike" and the spaced "share alike" both appear in real data and are
# both handled -- the latter as a two-token pair in the parser below, since
# it can't be a single dict key.
_CC_ELEMENT_WORDS: dict[str, str] = {
    "by": "by",
    "sa": "sa",
    "nc": "nc",
    "nd": "nd",
    "attribution": "by",
    "sharealike": "sa",
    "noncommercial": "nc",
    "noderivs": "nd",
    "noderivatives": "nd",
}

_VERSION_RE = re.compile(r"^\d+(\.\d+)?$")

# What's allowed after the version: CC's own non-jurisdiction qualifiers, a
# two-letter jurisdiction code, or a word from a spelled-out jurisdiction
# name. This is deliberately a broad allowlist, not an exhaustive one --
# "and so on" in the sense that new jurisdiction words can be added as they
# show up in real data -- but every token must clear it. A tail token that
# doesn't is prose ("not for commercial reuse"), and prose in a rights field
# means we don't actually know the terms.
_CC_TAIL_QUALIFIERS = frozenset({"international", "unported", "generic", "igo"})

_CC_JURISDICTION_WORDS = frozenset(
    {
        "germany",
        "austria",
        "france",
        "netherlands",
        "spain",
        "poland",
        "united",
        "kingdom",
        "states",
        "america",
        "new",
        "zealand",
        "czech",
        "republic",
        "belgium",
        "switzerland",
        "italy",
        "portugal",
        "sweden",
        "norway",
        "denmark",
        "finland",
        "greece",
        "hungary",
        "romania",
        "bulgaria",
        "croatia",
        "slovenia",
        "estonia",
        "ireland",
        "luxembourg",
        "malta",
        "scotland",
        "canada",
        "australia",
        "japan",
        "korea",
        "china",
        "brazil",
        "mexico",
        "chile",
        "argentina",
        "peru",
        "colombia",
        "africa",
        "south",
        "india",
        "israel",
        "singapore",
        "taiwan",
        "philippines",
        "thailand",
        "vietnam",
        "hong",
        "kong",
        "macau",
    }
)

# Pexels and Pixabay licenses are uniform across their catalogs, so a
# provider-wide default is safe. No other provider gets one -- everyone
# else's rights vary per item and must be resolved per item.
#
# Neither is legally CC0 -- each is a bespoke platform license, and recording
# it as CC0 would put a false statement in the database. PLATFORM_FREE names
# what it actually is: free commercial use, no attribution, per that
# platform's own terms rather than a public license.
_PROVIDER_DEFAULTS = {
    "pexels": LicenseType.PLATFORM_FREE,
    "pixabay": LicenseType.PLATFORM_FREE,
}

_WHITESPACE_RE = re.compile(r"\s+")
_NON_TOKEN_RE = re.compile(r"[^a-z0-9.]+")


def _normalize(value: str) -> str:
    lowered = value.strip().lower()
    collapsed = _NON_TOKEN_RE.sub(" ", lowered)
    collapsed = _WHITESPACE_RE.sub(" ", collapsed).strip()
    # Periods survive the substitution above (so "4.0" stays "4.0"), which
    # means a trailing sentence period ("Public domain.") or a stray leading
    # one survives too unless stripped separately here. Interior periods are
    # untouched -- this only trims the ends.
    return collapsed.strip(" .")


def _from_license_url(license_url: str) -> tuple[bool, LicenseType | None]:
    """Returns (matched, result). matched=False means "keep looking"."""
    parsed = urlparse(license_url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()

    if host == "creativecommons.org":
        if path.startswith("/publicdomain/zero/"):
            return True, LicenseType.CC0
        if path.startswith("/publicdomain/mark/"):
            return True, LicenseType.PUBLIC_DOMAIN
        if path.startswith("/licenses/by-sa/"):
            return True, LicenseType.CC_BY_SA
        if path.startswith("/licenses/by/"):
            return True, LicenseType.CC_BY
        # The host is a recognized rights authority, so an unmatched path
        # (by-nc, by-nd, and combinations) is a license we decline -- not an
        # unknown authority to keep searching past. It must not fall through
        # to a raw_rights template that would otherwise resolve.
        return True, None

    if host == "rightsstatements.org":
        # Every rightsstatements.org vocabulary term describes a copyright
        # status or restriction, not a grant: NoC-* means "no copyright
        # holder can enforce this here," InC-* means "in copyright," and the
        # rest (UND, CNE, NKC) mean "we don't know." None of that is a
        # license to use the work, so the whole namespace rejects.
        return True, None

    return False, None


def _tail_is_recognized(tail_tokens: list[str]) -> bool:
    """Every token after the version must be a qualifier we recognize: a
    known non-jurisdiction word (international, unported, generic, igo), a
    two-letter jurisdiction code, or a word from a spelled-out jurisdiction
    name. One token that isn't means the string carries something we don't
    understand -- e.g. "not for commercial reuse" -- and that's a reject,
    not something to silently drop.
    """
    for token in tail_tokens:
        if token in _CC_TAIL_QUALIFIERS or token in _CC_JURISDICTION_WORDS:
            continue
        if len(token) == 2 and token.isalpha():
            continue
        return False
    return True


def _parse_cc_attribution_family(normalized: str) -> tuple[bool, LicenseType | None]:
    """Structural parser for "cc"?/"creative commons"? + elements + version
    + jurisdiction?.

    Returns (matched, result). matched=False means this doesn't look like a
    CC attribution-family reference at all -- keep checking other templates.
    matched=True with result=None means it does, but doesn't resolve to
    anything in our vocabulary: NC or ND present (allowed only by
    construction of {by} and {by, sa}, not by an nc/nd denylist), the
    version is missing or malformed, or a trailing token after the version
    isn't a recognized jurisdiction/qualifier word (see _tail_is_recognized).
    """
    tokens = normalized.split(" ") if normalized else []
    idx = 0

    if idx < len(tokens) and tokens[idx] == "cc":
        idx += 1
    elif idx + 1 < len(tokens) and tokens[idx] == "creative" and tokens[idx + 1] == "commons":
        idx += 2
        # "Creative Commons" and "cc" are both prefix markers on their own,
        # but they also stack: "Creative Commons CC BY 4.0" is real usage,
        # not two competing spellings of the same thing.
        if idx < len(tokens) and tokens[idx] == "cc":
            idx += 1

    elements: set[str] = set()
    while idx < len(tokens):
        if tokens[idx] == "share" and idx + 1 < len(tokens) and tokens[idx + 1] == "alike":
            elements.add("sa")
            idx += 2
            continue
        if tokens[idx] in _CC_ELEMENT_WORDS:
            elements.add(_CC_ELEMENT_WORDS[tokens[idx]])
            idx += 1
            continue
        break

    if not elements:
        return False, None

    if idx >= len(tokens) or not _VERSION_RE.match(tokens[idx]):
        return True, None
    idx += 1

    if not _tail_is_recognized(tokens[idx:]):
        return True, None

    if elements == {"by"}:
        return True, LicenseType.CC_BY
    if elements == {"by", "sa"}:
        return True, LicenseType.CC_BY_SA
    return True, None


def _from_template(raw_rights: str) -> LicenseType | None:
    normalized = _normalize(raw_rights)
    if not normalized:
        return None
    if normalized in _CC0_TEMPLATES:
        return LicenseType.CC0
    if normalized in _PUBLIC_DOMAIN_TEMPLATES:
        return LicenseType.PUBLIC_DOMAIN
    matched, result = _parse_cc_attribution_family(normalized)
    if matched:
        return result
    return None


def resolve(raw_rights: str | None, license_url: str | None, provider: str) -> LicenseType | None:
    if license_url:
        matched, result = _from_license_url(license_url)
        if matched:
            return result

    if raw_rights:
        result = _from_template(raw_rights)
        if result is not None:
            return result

    return _PROVIDER_DEFAULTS.get(provider.strip().lower())


def requires_attribution(license: LicenseType) -> bool:
    """CC_BY and CC_BY_SA are the only licenses in our vocabulary that carry
    an attribution term. CC0 and PUBLIC_DOMAIN carry none by definition;
    PLATFORM_FREE is a no-attribution grant by its platform's own terms;
    LICENSED and GENERATED are handled by whatever receipt or generation
    record backs them, not this module.
    """
    return license in (LicenseType.CC_BY, LicenseType.CC_BY_SA)


def share_alike_obligation(license: LicenseType) -> bool:
    """True only for CC_BY_SA -- the one license in our vocabulary whose
    terms extend to derivative works, not just the original asset. The
    render pipeline decides whether that's acceptable for a given episode;
    this just flags it.
    """
    return license == LicenseType.CC_BY_SA
