"""resolve() against every fixture in tests/fixtures/rights_strings.json.

The fixture file is the actual asset (per docs/ARCHIVE-SPEC.md); this test
just walks it. Adding a case there is enough to cover it here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.archive.licensing import (
    _CC0_TEMPLATES,
    _PUBLIC_DOMAIN_TEMPLATES,
    _normalize,
    requires_attribution,
    resolve,
    share_alike_obligation,
)
from packages.domain.enums import LicenseType

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "rights_strings.json"


def _load_fixtures() -> list[dict[str, Any]]:
    with FIXTURES_PATH.open() as f:
        fixtures: list[dict[str, Any]] = json.load(f)
    return fixtures


FIXTURES = _load_fixtures()


def test_fixture_file_has_at_least_twenty_entries() -> None:
    assert len(FIXTURES) >= 20


def test_fixture_file_covers_both_resolved_and_rejected_cases() -> None:
    expectations = {entry["expected"] for entry in FIXTURES}
    assert None in expectations, "fixtures must include rejected (None) cases"
    assert expectations - {None}, "fixtures must include resolvable cases"


@pytest.mark.parametrize(
    "fixture",
    FIXTURES,
    ids=[entry["description"] for entry in FIXTURES],
)
def test_resolve_matches_fixture(fixture: dict[str, Any]) -> None:
    expected = LicenseType(fixture["expected"]) if fixture["expected"] is not None else None

    result = resolve(
        raw_rights=fixture["raw_rights"],
        license_url=fixture["license_url"],
        provider=fixture["provider"],
    )

    assert result == expected


# ---------------------------------------------------------------------------
# Targeted cases beyond the fixture sweep
# ---------------------------------------------------------------------------


def test_noc_prefixed_rightsstatements_reject() -> None:
    url = "https://rightsstatements.org/vocab/NoC-CR/1.0/"
    assert resolve(None, url, "internet_archive") is None


def test_inc_prefixed_rightsstatements_reject() -> None:
    assert resolve(None, "https://rightsstatements.org/vocab/InC-RUU/1.0/", "europeana") is None


def test_unrecognized_license_url_falls_through_to_none() -> None:
    assert resolve(None, "https://example.com/some-license", "internet_archive") is None


def test_none_raw_rights_and_none_license_url_and_unknown_provider() -> None:
    assert resolve(None, None, "unknown_provider") is None


def test_url_match_takes_priority_over_conflicting_template() -> None:
    """Most-specific-first: a rejecting URL wins even if raw_rights alone would resolve."""
    result = resolve(
        raw_rights="CC0",
        license_url="http://rightsstatements.org/vocab/InC/1.0/",
        provider="europeana",
    )
    assert result is None


def test_unmatched_creativecommons_path_rejects_and_does_not_fall_through() -> None:
    """A recognized authority (creativecommons.org) with an unmatched path (by-nc-nd)
    is a decline, not an unknown authority -- it must not fall through to a
    permissive raw_rights template.
    """
    result = resolve(
        raw_rights="CC0",
        license_url="https://creativecommons.org/licenses/by-nc-nd/4.0/",
        provider="europeana",
    )
    assert result is None


@pytest.mark.parametrize("license", [LicenseType.CC_BY, LicenseType.CC_BY_SA])
def test_requires_attribution_true_for_cc_by_and_cc_by_sa(license: LicenseType) -> None:
    assert requires_attribution(license) is True


@pytest.mark.parametrize(
    "license",
    [
        LicenseType.CC0,
        LicenseType.PUBLIC_DOMAIN,
        LicenseType.YOUTUBE_AUDIO_LIBRARY,
        LicenseType.PLATFORM_FREE,
        LicenseType.LICENSED,
        LicenseType.GENERATED,
    ],
)
def test_requires_attribution_false_for_everything_else(license: LicenseType) -> None:
    assert requires_attribution(license) is False


def test_share_alike_obligation_true_only_for_cc_by_sa() -> None:
    assert share_alike_obligation(LicenseType.CC_BY_SA) is True


@pytest.mark.parametrize(
    "license",
    [
        LicenseType.CC0,
        LicenseType.PUBLIC_DOMAIN,
        LicenseType.YOUTUBE_AUDIO_LIBRARY,
        LicenseType.CC_BY,
        LicenseType.PLATFORM_FREE,
        LicenseType.LICENSED,
        LicenseType.GENERATED,
    ],
)
def test_share_alike_obligation_false_for_everything_else(license: LicenseType) -> None:
    assert share_alike_obligation(license) is False


# ---------------------------------------------------------------------------
# Template-set audit: every hand-written exact-match entry must be a fixed
# point of _normalize, or it can never match anything real (this is exactly
# how "pd us govedict" went dead -- it looked normalized but wasn't what
# _normalize actually produces from "PD-USGov-edict").
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", sorted(_PUBLIC_DOMAIN_TEMPLATES))
def test_public_domain_templates_round_trip_through_normalize(entry: str) -> None:
    assert _normalize(entry) == entry


@pytest.mark.parametrize("entry", sorted(_CC0_TEMPLATES))
def test_cc0_templates_round_trip_through_normalize(entry: str) -> None:
    assert _normalize(entry) == entry


# ---------------------------------------------------------------------------
# Structural CC parser: cases beyond the fixture sweep
# ---------------------------------------------------------------------------


def test_normalize_strips_trailing_period_but_keeps_interior_ones() -> None:
    assert _normalize("Public domain.") == "public domain"
    assert _normalize("CC BY 4.0") == "cc by 4.0"


def test_normalize_strips_leading_period() -> None:
    assert _normalize(".CC0") == "cc0"


@pytest.mark.parametrize(
    "raw_rights",
    [
        "CC BY-NC-ND 4.0",
        "CC BY-NC-SA 4.0",
        "Attribution-NonCommercial-ShareAlike 4.0 International",
    ],
)
def test_cc_elements_outside_by_and_by_sa_reject(raw_rights: str) -> None:
    """Rejected by construction: {by} and {by, sa} are the only allowed
    element sets, so anything containing nc or nd falls through the
    allowlist regardless of how many elements are combined.
    """
    assert resolve(raw_rights, None, "wikimedia") is None


@pytest.mark.parametrize(
    "raw_rights",
    [
        "Creative Commons Attribution 4.0 International",
        "Creative Commons Attribution-ShareAlike 4.0 International",
        "Creative Commons CC BY 4.0",
    ],
)
def test_creative_commons_long_prefix_is_stripped(raw_rights: str) -> None:
    assert resolve(raw_rights, None, "wikimedia") is not None


def test_share_alike_spaced_tokens_match_like_the_compound_word() -> None:
    assert resolve("CC BY Share Alike 4.0", None, "wikimedia") == LicenseType.CC_BY_SA
    assert resolve("CC BY-SA 4.0", None, "wikimedia") == resolve(
        "CC BY Share Alike 4.0", None, "wikimedia"
    )


def test_tail_rejects_unrecognized_prose() -> None:
    """A real version number wrapped in a restriction must not resolve --
    ignoring the tail would discard the restriction and grant CC_BY anyway.
    """
    assert resolve("CC BY 4.0 not for commercial reuse", None, "internet_archive") is None


@pytest.mark.parametrize(
    "raw_rights",
    [
        "CC BY-SA 3.0 Czech Republic",
        "CC BY 3.0 New Zealand",
        "CC BY-SA 3.0 DE",
    ],
)
def test_tail_accepts_known_jurisdiction_words(raw_rights: str) -> None:
    assert resolve(raw_rights, None, "wikimedia") is not None
