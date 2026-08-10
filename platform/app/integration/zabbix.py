import logging

import httpx

logger = logging.getLogger(__name__)


class ZabbixApiClient:
    def __init__(self, api_url: str, token: str):
        self._api_url = api_url
        self._token = token

    async def open_problems(self) -> list[dict]:
        payload = {
            "jsonrpc": "2.0",
            "method": "problem.get",
            "params": {
                "output": ["eventid", "name", "severity", "clock", "opdata"],
                "selectHosts": ["host"],
                "selectTags": "extend",
                "recent": True,
                "suppressed": False,
                "sortfield": ["eventid"],
                "sortorder": "DESC",
            },
            "id": 1,
        }
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self._api_url, json=payload, headers=headers)
            response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("data", "Zabbix API error"))
        return body["result"]
