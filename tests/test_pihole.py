import json
from unittest import mock

import httpx
import pytest

from app.pihole import (
    PiHoleAPIError,
    PiHoleClient,
    PiHoleResponseError,
    PiHoleUnavailableError,
)

BASE_URL = "http://192.168.1.115"


def mock_http_client(response=None, side_effect=None):
    client = mock.MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    if side_effect is not None:
        client.get = mock.AsyncMock(side_effect=side_effect)
    else:
        client.get = mock.AsyncMock(return_value=response)
    return client


@pytest.mark.asyncio
async def test_get_groups_returns_payload():
    payload = {
        "groups": [
            {"id": 0, "name": "Default", "enabled": True, "comment": None},
            {"id": 1, "name": "kids-restricted", "enabled": False, "comment": None},
            {"id": 3, "name": "TV", "enabled": False, "comment": None},
        ]
    }

    response = mock.Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None

    http_client = mock_http_client(response=response)

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(f"{BASE_URL}/")
        result = await client.get_groups()

    assert result == payload
    http_client.get.assert_awaited_once_with(f"{BASE_URL}/api/groups")


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [404, 500])
async def test_get_groups_raises_on_api_error(status_code):
    request = httpx.Request("GET", f"{BASE_URL}/api/groups")
    error = httpx.HTTPStatusError(
        "API error",
        request=request,
        response=httpx.Response(status_code, request=request),
    )

    response = mock.Mock()
    response.raise_for_status.side_effect = error

    http_client = mock_http_client(response=response)

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(PiHoleAPIError, match=f"HTTP {status_code}"):
            await client.get_groups()


@pytest.mark.asyncio
async def test_get_groups_raises_when_unavailable():
    http_client = mock_http_client(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(PiHoleUnavailableError, match="Could not reach Pi-hole"):
            await client.get_groups()


@pytest.mark.asyncio
async def test_get_groups_raises_on_invalid_json():
    response = mock.Mock()
    response.json.side_effect = json.JSONDecodeError(
        "Expecting value", "not json", 0
    )
    response.raise_for_status.return_value = None

    http_client = mock_http_client(response=response)

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(PiHoleResponseError, match="invalid JSON"):
            await client.get_groups()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "not a dict",
        42,
        {},
        {"groups": "not a list"},
        {"groups": [{}]},
        {"groups": ["not a dict"]},
        {"groups": [{"id": 1, "name": "TV"}]},
    ],
)
async def test_get_groups_raises_on_unexpected_shape(payload):
    response = mock.Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None

    http_client = mock_http_client(response=response)

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(PiHoleResponseError, match="unexpected response"):
            await client.get_groups()
