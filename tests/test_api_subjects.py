from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.domain.enums import MonetizationTier, ResolutionStatus
from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG
from packages.strategies.criminal_cases.enums import CaseType, RiskFlag


def _subject_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "strategy_slug": CRIMINAL_CASES_SLUG,
        "slug": "test-subject",
        "title": "Test Subject",
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


def test_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEFILE_DB_PATH", ":memory:")
    app = create_app()
    with TestClient(app) as test_client:
        response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_preview_eligibility_red_for_child_victim_touches_no_db(client: TestClient) -> None:
    payload = _subject_payload(slug="preview-only", risk_flags=[RiskFlag.CHILD_VICTIM.value])

    response = client.post("/subjects/preview-eligibility", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == MonetizationTier.RED.value
    assert any("CHILD_VICTIM" in note for note in body["notes"])

    listing = client.get("/subjects")
    assert listing.json()["total"] == 0


def test_preview_eligibility_rejects_unknown_strategy(client: TestClient) -> None:
    payload = _subject_payload(slug="preview-bad-strategy", strategy_slug="not-a-real-strategy")

    response = client.post("/subjects/preview-eligibility", json=payload)

    assert response.status_code == 422


def test_create_subject_rejects_extra_monetization_tier_key(client: TestClient) -> None:
    payload = _subject_payload(slug="hand-set-tier")
    payload["monetization_tier"] = "green"

    response = client.post("/subjects", json=payload)

    assert response.status_code == 422

    listing = client.get("/subjects")
    assert listing.json()["total"] == 0


def test_create_subject_computes_tier_server_side(client: TestClient) -> None:
    payload = _subject_payload(
        slug="computed-tier", risk_flags=[RiskFlag.CHILD_VICTIM.value]
    )

    response = client.post("/subjects", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["monetization_tier"] == MonetizationTier.RED.value
    assert body["attributes"] == {"case_type": CaseType.HOMICIDE.value}


def test_create_subject_rejects_unknown_strategy(client: TestClient) -> None:
    payload = _subject_payload(slug="bad-strategy", strategy_slug="not-a-real-strategy")

    response = client.post("/subjects", json=payload)

    assert response.status_code == 422


def test_create_subject_rejects_invalid_attributes(client: TestClient) -> None:
    payload = _subject_payload(slug="bad-attributes", attributes={"case_type": "not_real"})

    response = client.post("/subjects", json=payload)

    assert response.status_code == 422


def test_create_subject_rejects_unrecognized_risk_flag(client: TestClient) -> None:
    payload = _subject_payload(slug="bad-flag", risk_flags=["not_a_real_flag"])

    response = client.post("/subjects", json=payload)

    assert response.status_code == 422


def test_list_subjects_filters_actually_filter(client: TestClient) -> None:
    client.post("/subjects", json=_subject_payload(slug="subject-1"))
    client.post(
        "/subjects",
        json=_subject_payload(
            slug="subject-2",
            attributes={"case_type": CaseType.DISAPPEARANCE.value},
        ),
    )
    client.post(
        "/subjects",
        json=_subject_payload(slug="red-subject", risk_flags=[RiskFlag.CHILD_VICTIM.value]),
    )

    unfiltered = client.get("/subjects")
    assert unfiltered.json()["total"] == 3

    by_tier = client.get("/subjects", params={"monetization_tier": MonetizationTier.RED.value})
    assert by_tier.json()["total"] == 1
    assert by_tier.json()["items"][0]["slug"] == "red-subject"

    by_strategy = client.get("/subjects", params={"strategy_slug": CRIMINAL_CASES_SLUG})
    assert by_strategy.json()["total"] == 3

    by_unknown_strategy = client.get("/subjects", params={"strategy_slug": "not-a-real-strategy"})
    assert by_unknown_strategy.json()["total"] == 0


def test_get_and_update_subject(client: TestClient) -> None:
    create_response = client.post("/subjects", json=_subject_payload(slug="updatable"))
    subject_id = create_response.json()["id"]

    get_response = client.get(f"/subjects/{subject_id}")
    assert get_response.status_code == 200
    assert get_response.json()["slug"] == "updatable"

    update_response = client.patch(f"/subjects/{subject_id}", json={"title": "Updated Title"})
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Updated Title"


def test_delete_subject(client: TestClient) -> None:
    create_response = client.post("/subjects", json=_subject_payload(slug="deletable"))
    subject_id = create_response.json()["id"]

    delete_response = client.delete(f"/subjects/{subject_id}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/subjects/{subject_id}")
    assert get_response.status_code == 404
