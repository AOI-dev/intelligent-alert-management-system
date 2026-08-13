import logging

import httpx

logger = logging.getLogger(__name__)


class ZabbixApiClient:
    def __init__(self, api_url: str, token: str):
        self._api_url = api_url
        self._token = token

    async def _call(self, client: httpx.AsyncClient, method: str, params: dict) -> list[dict]:
        response = await client.post(
            self._api_url,
            json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("data", f"Zabbix API error in {method}"))
        return body["result"]

    async def open_problems(self) -> list[dict]:
        """Current problems, each with its host attached under "hosts".

        Two calls, not one, because `problem.get` has no `selectHosts` --
        asking for it fails the whole request with `unexpected parameter
        "selectHosts"`, which is what every reconciliation cycle was doing.
        A problem points at a trigger via `objectid`, and `trigger.get` is
        where the host lives, so the hosts are fetched in one batched
        follow-up and attached in the shape normalize_zabbix_problem already
        expects. It reads `problem["hosts"][0]["host"]` and falls back to
        "unknown", so a problem whose trigger has vanished still normalizes.
        """
        async with httpx.AsyncClient(timeout=10) as client:
            problems = await self._call(
                client,
                "problem.get",
                {
                    "output": ["eventid", "name", "severity", "clock", "opdata", "objectid"],
                    "selectTags": "extend",
                    "recent": True,
                    "suppressed": False,
                    "sortfield": ["eventid"],
                    "sortorder": "DESC",
                },
            )
            trigger_ids = sorted({str(p["objectid"]) for p in problems if p.get("objectid")})
            if not trigger_ids:
                return problems

            triggers = await self._call(
                client,
                "trigger.get",
                {"output": ["triggerid"], "triggerids": trigger_ids, "selectHosts": ["host"]},
            )

        hosts_by_trigger = {str(t["triggerid"]): t.get("hosts", []) for t in triggers}
        for problem in problems:
            problem["hosts"] = hosts_by_trigger.get(str(problem.get("objectid")), [])
        return problems
