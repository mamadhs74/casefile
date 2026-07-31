from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from packages.domain.enums import CaseType, ResolutionStatus, SourceTier


def _case_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slug": "source-test-case",
        "title": "Source Test Case",
        "case_type": CaseType.HOMICIDE.value,
        "event_year": 1950,
        "country": "US",
        "summary": "A test case.",
        "resolution_status": ResolutionStatus.CONVICTED.value,
        "living_persons_involved": False,
        "risk_flags": [],
        "documentation_score": 4,
    }
    payload.update(overrides)
    return payload


def _source_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": "https://www.bbc.co.uk/news/article-1",
        "publisher": "BBC",
        "title": "An article",
        "tier": SourceTier.PRIMARY_RECORD.value,
        "text_path": "/tmp/text.txt",
        "text_sha256": "0" * 64,
        "word_count": 500,
    }
    payload.update(overrides)
    return payload


def _create_case(client: TestClient, **overrides: Any) -> int:
    response = client.post("/cases", json=_case_payload(**overrides))
    assert response.status_code == 201
    case_id: int = response.json()["id"]
    return case_id


def test_create_source_derives_domain_from_url(client: TestClient) -> None:
    case_id = _create_case(client, slug="case-for-sources")

    response = client.post(
        f"/cases/{case_id}/sources",
        json=_source_payload(url="https://www.bbc.co.uk/news/article-1"),
    )

    assert response.status_code == 201
    assert response.json()["domain"] == "bbc.co.uk"


def test_create_source_rejects_client_supplied_domain(client: TestClient) -> None:
    case_id = _create_case(client, slug="case-reject-domain")

    payload = _source_payload(url="https://example.com/1")
    payload["domain"] = "attacker-supplied.example"

    response = client.post(f"/cases/{case_id}/sources", json=payload)

    assert response.status_code == 422


def test_list_sources_returns_created_sources(client: TestClient) -> None:
    case_id = _create_case(client, slug="case-with-sources")
    client.post(f"/cases/{case_id}/sources", json=_source_payload(url="https://a.com/1"))
    client.post(f"/cases/{case_id}/sources", json=_source_payload(url="https://b.com/1"))

    response = client.get(f"/cases/{case_id}/sources")

    assert response.status_code == 200
    domains = {source["domain"] for source in response.json()}
    assert domains == {"a.com", "b.com"}


def test_sources_endpoints_404_for_unknown_case(client: TestClient) -> None:
    assert client.get("/cases/999/sources").status_code == 404
    assert client.post("/cases/999/sources", json=_source_payload()).status_code == 404


def test_gate_endpoint_fails_before_enough_sources(client: TestClient) -> None:
    case_id = _create_case(client, slug="gate-not-ready")

    response = client.get(f"/cases/{case_id}/gate")

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is False
    assert "insufficient_verified_sources" in body["reasons"]
    assert "missing_primary_record" in body["reasons"]


def test_gate_endpoint_passes_with_three_independent_sources(client: TestClient) -> None:
    case_id = _create_case(client, slug="gate-ready")
    client.post(
        f"/cases/{case_id}/sources",
        json=_source_payload(url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD.value),
    )
    client.post(
        f"/cases/{case_id}/sources",
        json=_source_payload(url="https://b.com/1", tier=SourceTier.CONTEMPORANEOUS.value),
    )
    client.post(
        f"/cases/{case_id}/sources",
        json=_source_payload(url="https://c.com/1", tier=SourceTier.RETROSPECTIVE.value),
    )

    response = client.get(f"/cases/{case_id}/gate")

    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is True
    assert body["reasons"] == []
    assert body["distinct_domain_count"] == 3


def test_gate_endpoint_fails_when_subdomains_collapse(client: TestClient) -> None:
    case_id = _create_case(client, slug="gate-collapsed-domains")
    for url, tier in (
        ("https://www.bbc.co.uk/1", SourceTier.PRIMARY_RECORD.value),
        ("https://bbc.co.uk/2", SourceTier.CONTEMPORANEOUS.value),
        ("https://amp.bbc.co.uk/3", SourceTier.RETROSPECTIVE.value),
    ):
        client.post(f"/cases/{case_id}/sources", json=_source_payload(url=url, tier=tier))

    response = client.get(f"/cases/{case_id}/gate")

    body = response.json()
    assert body["passed"] is False
    assert "insufficient_distinct_domains" in body["reasons"]
    assert body["distinct_domain_count"] == 1


def test_gate_endpoint_404_for_unknown_case(client: TestClient) -> None:
    assert client.get("/cases/999/gate").status_code == 404
