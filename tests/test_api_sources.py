from __future__ import annotations

import hashlib
from typing import Any

from fastapi.testclient import TestClient

from packages.domain.enums import ResolutionStatus, SourceTier
from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG
from packages.strategies.criminal_cases.enums import CaseType


def _subject_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "strategy_slug": CRIMINAL_CASES_SLUG,
        "slug": "source-test-subject",
        "title": "Source Test Subject",
        "attributes": {"case_type": CaseType.HOMICIDE.value},
        "event_year": 1950,
        "country": "US",
        "summary": "A test subject.",
        "resolution_status": ResolutionStatus.CONVICTED.value,
        "living_persons_involved": False,
        "risk_flags": [],
        "documentation_score": 4,
    }
    payload.update(overrides)
    return payload


def _source_payload(**overrides: Any) -> dict[str, Any]:
    # text_sha256 defaults to a hash of url, not a fixed value -- Source.
    # text_sha256 is unique per (subject_id, text_sha256), and a shared
    # constant here would model two sources with byte-identical content.
    url = overrides.get("url", "https://www.bbc.co.uk/news/article-1")
    payload: dict[str, Any] = {
        "url": url,
        "publisher": "BBC",
        "title": "An article",
        "tier": SourceTier.PRIMARY_RECORD.value,
        "text_path": "/tmp/text.txt",
        "text_sha256": hashlib.sha256(url.encode()).hexdigest(),
        "word_count": 500,
    }
    payload.update(overrides)
    return payload


def _create_subject(client: TestClient, **overrides: Any) -> int:
    response = client.post("/subjects", json=_subject_payload(**overrides))
    assert response.status_code == 201
    subject_id: int = response.json()["id"]
    return subject_id


def test_create_source_derives_domain_from_url(client: TestClient) -> None:
    subject_id = _create_subject(client, slug="subject-for-sources")

    response = client.post(
        f"/subjects/{subject_id}/sources",
        json=_source_payload(url="https://www.bbc.co.uk/news/article-1"),
    )

    assert response.status_code == 201
    assert response.json()["domain"] == "bbc.co.uk"


def test_create_source_rejects_client_supplied_domain(client: TestClient) -> None:
    subject_id = _create_subject(client, slug="subject-reject-domain")

    payload = _source_payload(url="https://example.com/1")
    payload["domain"] = "attacker-supplied.example"

    response = client.post(f"/subjects/{subject_id}/sources", json=payload)

    assert response.status_code == 422


def test_list_sources_returns_created_sources(client: TestClient) -> None:
    subject_id = _create_subject(client, slug="subject-with-sources")
    client.post(f"/subjects/{subject_id}/sources", json=_source_payload(url="https://a.com/1"))
    client.post(f"/subjects/{subject_id}/sources", json=_source_payload(url="https://b.com/1"))

    response = client.get(f"/subjects/{subject_id}/sources")

    assert response.status_code == 200
    domains = {source["domain"] for source in response.json()}
    assert domains == {"a.com", "b.com"}


def test_sources_endpoints_404_for_unknown_subject(client: TestClient) -> None:
    assert client.get("/subjects/999/sources").status_code == 404
    assert client.post("/subjects/999/sources", json=_source_payload()).status_code == 404


def test_gate_endpoint_fails_before_enough_sources(client: TestClient) -> None:
    subject_id = _create_subject(client, slug="gate-not-ready")

    response = client.get(f"/subjects/{subject_id}/gate")

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is False
    assert "insufficient_verified_sources" in body["reasons"]
    assert "missing_primary_record" in body["reasons"]


def test_gate_endpoint_passes_with_three_independent_sources(client: TestClient) -> None:
    subject_id = _create_subject(client, slug="gate-ready")
    client.post(
        f"/subjects/{subject_id}/sources",
        json=_source_payload(url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD.value),
    )
    client.post(
        f"/subjects/{subject_id}/sources",
        json=_source_payload(url="https://b.com/1", tier=SourceTier.CONTEMPORANEOUS.value),
    )
    client.post(
        f"/subjects/{subject_id}/sources",
        json=_source_payload(url="https://c.com/1", tier=SourceTier.RETROSPECTIVE.value),
    )

    response = client.get(f"/subjects/{subject_id}/gate")

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is True
    assert body["reasons"] == []
    assert body["distinct_domain_count"] == 3


def test_gate_endpoint_fails_when_subdomains_collapse(client: TestClient) -> None:
    subject_id = _create_subject(client, slug="gate-collapsed-domains")
    for url, tier in (
        ("https://www.bbc.co.uk/1", SourceTier.PRIMARY_RECORD.value),
        ("https://bbc.co.uk/2", SourceTier.CONTEMPORANEOUS.value),
        ("https://amp.bbc.co.uk/3", SourceTier.RETROSPECTIVE.value),
    ):
        client.post(f"/subjects/{subject_id}/sources", json=_source_payload(url=url, tier=tier))

    response = client.get(f"/subjects/{subject_id}/gate")

    body = response.json()
    assert body["passed"] is False
    assert "insufficient_distinct_domains" in body["reasons"]
    assert body["distinct_domain_count"] == 1


def test_gate_endpoint_404_for_unknown_subject(client: TestClient) -> None:
    assert client.get("/subjects/999/gate").status_code == 404
