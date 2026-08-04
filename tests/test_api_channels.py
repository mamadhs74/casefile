from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG


def _channel_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "platform": "youtube",
        "display_name": "Casefile — Criminal Archive",
        "external_account_id": "UC1234567890",
        "credentials_ref": "casefile-youtube-criminal-cases",
    }
    payload.update(overrides)
    return payload


def test_list_channels_empty_for_new_strategy(client: TestClient) -> None:
    response = client.get(f"/strategies/{CRIMINAL_CASES_SLUG}/channels")

    assert response.status_code == 200
    assert response.json() == []


def test_create_channel_defaults_to_active(client: TestClient) -> None:
    response = client.post(f"/strategies/{CRIMINAL_CASES_SLUG}/channels", json=_channel_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["platform"] == "youtube"
    assert body["display_name"] == "Casefile — Criminal Archive"
    assert body["external_account_id"] == "UC1234567890"
    assert body["credentials_ref"] == "casefile-youtube-criminal-cases"
    assert body["is_active"] is True
    assert body["strategy_id"] is not None


def test_create_channel_rejects_credentials_field(client: TestClient) -> None:
    """No path in this API ever accepts credential material -- see CLAUDE.md."""
    payload = _channel_payload()
    payload["credentials"] = "sk-super-secret-token"

    response = client.post(f"/strategies/{CRIMINAL_CASES_SLUG}/channels", json=payload)

    assert response.status_code == 422


def test_create_channel_rejects_access_token_field(client: TestClient) -> None:
    payload = _channel_payload()
    payload["access_token"] = "sk-super-secret-token"

    response = client.post(f"/strategies/{CRIMINAL_CASES_SLUG}/channels", json=payload)

    assert response.status_code == 422


def test_list_channels_returns_created_channel(client: TestClient) -> None:
    client.post(f"/strategies/{CRIMINAL_CASES_SLUG}/channels", json=_channel_payload())

    response = client.get(f"/strategies/{CRIMINAL_CASES_SLUG}/channels")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_channels_404_for_unknown_strategy(client: TestClient) -> None:
    assert client.get("/strategies/not-a-real-strategy/channels").status_code == 404
    assert (
        client.post(
            "/strategies/not-a-real-strategy/channels", json=_channel_payload()
        ).status_code
        == 404
    )


def test_patch_deactivates_channel(client: TestClient) -> None:
    create_response = client.post(
        f"/strategies/{CRIMINAL_CASES_SLUG}/channels", json=_channel_payload()
    )
    channel_id = create_response.json()["id"]

    response = client.patch(
        f"/strategies/{CRIMINAL_CASES_SLUG}/channels/{channel_id}",
        json={"is_active": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    # untouched fields survive a partial update
    assert body["display_name"] == "Casefile — Criminal Archive"


def test_patch_rejects_credentials_field(client: TestClient) -> None:
    create_response = client.post(
        f"/strategies/{CRIMINAL_CASES_SLUG}/channels", json=_channel_payload()
    )
    channel_id = create_response.json()["id"]

    response = client.patch(
        f"/strategies/{CRIMINAL_CASES_SLUG}/channels/{channel_id}",
        json={"credentials": "sk-super-secret-token"},
    )

    assert response.status_code == 422


def test_patch_404_for_unknown_channel(client: TestClient) -> None:
    response = client.patch(
        f"/strategies/{CRIMINAL_CASES_SLUG}/channels/999",
        json={"is_active": False},
    )
    assert response.status_code == 404


def test_patch_404_for_unknown_strategy(client: TestClient) -> None:
    create_response = client.post(
        f"/strategies/{CRIMINAL_CASES_SLUG}/channels", json=_channel_payload()
    )
    channel_id = create_response.json()["id"]

    response = client.patch(
        f"/strategies/not-a-real-strategy/channels/{channel_id}",
        json={"is_active": False},
    )
    assert response.status_code == 404
