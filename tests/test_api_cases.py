from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.domain.enums import CaseType, MonetizationTier, ResolutionStatus, RiskFlag


def _case_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slug": "test-case",
        "title": "Test Case",
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


def test_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEFILE_DB_PATH", ":memory:")
    app = create_app()
    with TestClient(app) as test_client:
        response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_preview_eligibility_red_for_child_victim_touches_no_db(client: TestClient) -> None:
    payload = _case_payload(slug="preview-only", risk_flags=[RiskFlag.CHILD_VICTIM.value])

    response = client.post("/cases/preview-eligibility", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == MonetizationTier.RED.value
    assert any("CHILD_VICTIM" in note for note in body["notes"])

    listing = client.get("/cases")
    assert listing.json()["total"] == 0


def test_create_case_rejects_extra_monetization_tier_key(client: TestClient) -> None:
    payload = _case_payload(slug="hand-set-tier")
    payload["monetization_tier"] = "green"

    response = client.post("/cases", json=payload)

    assert response.status_code == 422

    listing = client.get("/cases")
    assert listing.json()["total"] == 0


def test_create_case_computes_tier_server_side(client: TestClient) -> None:
    payload = _case_payload(slug="computed-tier", risk_flags=[RiskFlag.CHILD_VICTIM.value])

    response = client.post("/cases", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["monetization_tier"] == MonetizationTier.RED.value


def test_list_cases_filters_actually_filter(client: TestClient) -> None:
    client.post("/cases", json=_case_payload(slug="homicide-1", case_type=CaseType.HOMICIDE.value))
    client.post(
        "/cases",
        json=_case_payload(slug="disappearance-1", case_type=CaseType.DISAPPEARANCE.value),
    )
    client.post(
        "/cases",
        json=_case_payload(
            slug="red-case",
            case_type=CaseType.HOMICIDE.value,
            risk_flags=[RiskFlag.CHILD_VICTIM.value],
        ),
    )

    unfiltered = client.get("/cases")
    assert unfiltered.json()["total"] == 3

    by_type = client.get("/cases", params={"case_type": CaseType.DISAPPEARANCE.value})
    assert by_type.json()["total"] == 1
    assert by_type.json()["items"][0]["slug"] == "disappearance-1"

    by_tier = client.get("/cases", params={"monetization_tier": MonetizationTier.RED.value})
    assert by_tier.json()["total"] == 1
    assert by_tier.json()["items"][0]["slug"] == "red-case"
