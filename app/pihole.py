import httpx


class PiHoleClient:

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def get_groups(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/groups"
            )

            response.raise_for_status()

            return response.json()