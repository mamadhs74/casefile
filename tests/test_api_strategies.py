from __future__ import annotations

from fastapi.testclient import TestClient

from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG


def test_list_strategies_includes_seeded_strategy(client: TestClient) -> None:
    response = client.get("/strategies")

    assert response.status_code == 200
    slugs = {item["slug"] for item in response.json()}
    assert CRIMINAL_CASES_SLUG in slugs


def test_get_strategy_by_slug(client: TestClient) -> None:
    response = client.get(f"/strategies/{CRIMINAL_CASES_SLUG}")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == CRIMINAL_CASES_SLUG
    assert body["min_verified_sources"] == 3


def test_get_strategy_404_for_unknown_slug(client: TestClient) -> None:
    response = client.get("/strategies/not-a-real-strategy")

    assert response.status_code == 404
