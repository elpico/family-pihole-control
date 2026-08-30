from urllib.parse import quote

import httpx


class PiHoleError(Exception):
    pass


class PiHoleUnavailableError(PiHoleError):
    pass


class PiHoleAPIError(PiHoleError):
    pass


class PiHoleResponseError(PiHoleError):
    pass


class PiHoleClient:

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def get_groups(self):
        payload = await self._request("GET", "/api/groups")

        self.validate_groups(payload)

        return payload

    async def replace_group(self, name, comment, enabled):
        payload = await self._request(
            "PUT",
            f"/api/groups/{quote(name, safe='')}",
            {"name": name, "comment": comment, "enabled": enabled},
        )
        self.validate_groups(payload)
        return payload

    async def _request(self, method: str, path: str, json_body=None):
        url = f"{self.base_url}{path}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, json=json_body)
                response.raise_for_status()
                payload = response.json()
        except httpx.TransportError as exc:
            raise PiHoleUnavailableError(
                f"Could not reach Pi-hole at {self.base_url}."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise PiHoleAPIError(
                f"Pi-hole API error: HTTP {exc.response.status_code}."
            ) from exc
        except ValueError as exc:
            raise PiHoleResponseError(
                "Pi-hole returned invalid JSON."
            ) from exc

        return payload

    @staticmethod
    def validate_groups(payload):
        if not isinstance(payload, dict) or not isinstance(
            payload.get("groups"), list
        ):
            raise PiHoleResponseError(
                "Pi-hole returned an unexpected response."
            )

        for group in payload["groups"]:
            if not isinstance(group, dict) or not {
                "id", "name", "enabled"
            } <= group.keys():
                raise PiHoleResponseError(
                    "Pi-hole returned an unexpected response."
                )
