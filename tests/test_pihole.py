import json
from unittest import mock
from urllib.parse import quote

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
        client.request = mock.AsyncMock(side_effect=side_effect)
    else:
        client.request = mock.AsyncMock(return_value=response)
    return client


def mock_response(payload=None, json_side_effect=None, raise_for_status=None):
    response = mock.Mock()
    if json_side_effect is not None:
        response.json.side_effect = json_side_effect
    else:
        response.json.return_value = payload
    if raise_for_status is not None:
        response.raise_for_status.side_effect = raise_for_status
    else:
        response.raise_for_status.return_value = None
    return response


def api_error(status_code, url):
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError(
        "API error",
        request=request,
        response=httpx.Response(status_code, request=request),
    )


GROUPS_PAYLOAD = {
    "groups": [
        {"id": 0, "name": "Default", "enabled": False, "comment": None},
        {"id": 3, "name": "streaming", "enabled": True, "comment": "content"},
        {"id": 2, "name": "orla", "enabled": False, "comment": None},
    ]
}


@pytest.mark.asyncio
async def test_get_groups_returns_payload():
    http_client = mock_http_client(response=mock_response(GROUPS_PAYLOAD))

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(f"{BASE_URL}/")
        result = await client.get_groups()

    assert result == GROUPS_PAYLOAD
    http_client.request.assert_awaited_once_with(
        "GET", f"{BASE_URL}/api/groups", json=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [404, 500])
async def test_get_groups_raises_on_api_error(status_code):
    http_client = mock_http_client(
        response=mock_response(
            raise_for_status=api_error(
                status_code, f"{BASE_URL}/api/groups"
            )
        )
    )

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
        with pytest.raises(
            PiHoleUnavailableError, match="Could not reach Pi-hole"
        ):
            await client.get_groups()


@pytest.mark.asyncio
async def test_get_groups_raises_on_invalid_json():
    http_client = mock_http_client(
        response=mock_response(
            json_side_effect=json.JSONDecodeError(
                "Expecting value", "not json", 0
            )
        )
    )

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
    http_client = mock_http_client(response=mock_response(payload))

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(
            PiHoleResponseError, match="unexpected response"
        ):
            await client.get_groups()


@pytest.mark.asyncio
async def test_replace_group_puts_to_group_endpoint():
    payload = {
        "groups": [
            {
                "id": 3,
                "name": "streaming",
                "enabled": True,
                "comment": "content",
            }
        ]
    }

    http_client = mock_http_client(response=mock_response(payload))

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        result = await client.replace_group("streaming", "content", True)

    assert result == payload
    http_client.request.assert_awaited_once_with(
        "PUT",
        f"{BASE_URL}/api/groups/streaming",
        json={"name": "streaming", "comment": "content", "enabled": True},
    )


@pytest.mark.asyncio
async def test_replace_group_uri_escapes_group_name():
    name = "my group"
    payload = {"groups": []}

    http_client = mock_http_client(response=mock_response(payload))

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        await client.replace_group(name, None, False)

    http_client.request.assert_awaited_once_with(
        "PUT",
        f"{BASE_URL}/api/groups/{quote(name, safe='')}",
        json={"name": name, "comment": None, "enabled": False},
    )


@pytest.mark.asyncio
async def test_replace_group_echoes_comment_verbatim():
    payload = {
        "groups": [
            {
                "id": 7,
                "name": "social-media",
                "enabled": True,
                "comment": "social media ",
            }
        ]
    }

    http_client = mock_http_client(response=mock_response(payload))

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        await client.replace_group("social-media", "social media ", True)

    http_client.request.assert_awaited_once_with(
        "PUT",
        f"{BASE_URL}/api/groups/social-media",
        json={
            "name": "social-media",
            "comment": "social media ",
            "enabled": True,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 404, 500])
async def test_replace_group_raises_on_api_error(status_code):
    http_client = mock_http_client(
        response=mock_response(
            raise_for_status=api_error(
                status_code, f"{BASE_URL}/api/groups/streaming"
            )
        )
    )

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(PiHoleAPIError, match=f"HTTP {status_code}"):
            await client.replace_group("streaming", None, True)


@pytest.mark.asyncio
async def test_replace_group_raises_when_unavailable():
    http_client = mock_http_client(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(
            PiHoleUnavailableError, match="Could not reach Pi-hole"
        ):
            await client.replace_group("streaming", None, True)


@pytest.mark.asyncio
async def test_replace_group_raises_on_invalid_json():
    http_client = mock_http_client(
        response=mock_response(
            json_side_effect=json.JSONDecodeError(
                "Expecting value", "not json", 0
            )
        )
    )

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(PiHoleResponseError, match="invalid JSON"):
            await client.replace_group("streaming", None, True)


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
async def test_replace_group_raises_on_unexpected_shape(payload):
    http_client = mock_http_client(response=mock_response(payload))

    with mock.patch("app.pihole.httpx.AsyncClient", return_value=http_client):
        client = PiHoleClient(BASE_URL)
        with pytest.raises(
            PiHoleResponseError, match="unexpected response"
        ):
            await client.replace_group("streaming", None, True)
