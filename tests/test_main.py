from unittest import mock

from fastapi.testclient import TestClient

from app import main
from app.pihole import (
    PiHoleAPIError,
    PiHoleResponseError,
    PiHoleUnavailableError,
)

client = TestClient(main.app)


def test_home_shows_groups():
    payload = {
        "groups": [
            {"id": 0, "name": "Default", "enabled": True},
            {"id": 1, "name": "kids-restricted", "enabled": False},
        ]
    }

    with mock.patch.object(
        main.pihole, "get_groups", new=mock.AsyncMock(return_value=payload)
    ):
        response = client.get("/")

    assert response.status_code == 200
    assert "Default" in response.text
    assert "kids-restricted" in response.text
    assert "ON" in response.text
    assert "OFF" in response.text


def test_home_shows_message_when_pihole_unavailable():
    with mock.patch.object(
        main.pihole,
        "get_groups",
        new=mock.AsyncMock(
            side_effect=PiHoleUnavailableError(
                f"Could not reach Pi-hole at {main.pihole.base_url}."
            )
        ),
    ):
        response = client.get("/")

    assert response.status_code == 200
    assert "Could not reach Pi-hole" in response.text
    assert "Pi-hole Groups" not in response.text


def test_home_shows_message_on_api_error():
    with mock.patch.object(
        main.pihole,
        "get_groups",
        new=mock.AsyncMock(
            side_effect=PiHoleAPIError("Pi-hole API error: HTTP 500.")
        ),
    ):
        response = client.get("/")

    assert response.status_code == 200
    assert "Pi-hole API error: HTTP 500." in response.text
    assert "Pi-hole Groups" not in response.text


def test_home_shows_message_on_unexpected_response():
    with mock.patch.object(
        main.pihole,
        "get_groups",
        new=mock.AsyncMock(
            side_effect=PiHoleResponseError(
                "Pi-hole returned an unexpected response."
            )
        ),
    ):
        response = client.get("/")

    assert response.status_code == 200
    assert "Pi-hole returned an unexpected response." in response.text
    assert "Pi-hole Groups" not in response.text
