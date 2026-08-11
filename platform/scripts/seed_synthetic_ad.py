"""Link any identity that has logged in via TrueConf OAuth but has no AD
attributes yet to a synthetic Active Directory record: a fake login,
department, and team drawn from a small fixture org chart.

This is deliberately not a real AD sync (АР-07: AD is a nominal attribute
source for the pilot, all data synthetic). Run after a batch of test users
have logged in at least once through /v1/auth/login:

    cd platform && python -m scripts.seed_synthetic_ad
"""
import asyncio
import itertools

from app.identity.db import SessionLocal
from app.identity.repository import link_ad_account, list_identities

SYNTHETIC_ORG_CHART = [
    {"department": "NOC", "team": "noc-shift-a", "manager_ad_login": "ad-noc-lead"},
    {"department": "NOC", "team": "noc-shift-b", "manager_ad_login": "ad-noc-lead"},
    {"department": "SRE", "team": "sre-platform", "manager_ad_login": "ad-sre-lead"},
    {"department": "SRE", "team": "sre-network", "manager_ad_login": "ad-sre-lead"},
]


async def main() -> None:
    async with SessionLocal() as session:
        identities = [identity for identity in await list_identities(session) if identity.ad_link is None]
        if not identities:
            print("No unlinked identities found — have any test users logged in yet?")
            return
        org_chart = itertools.cycle(SYNTHETIC_ORG_CHART)
        for index, identity in enumerate(identities):
            slot = next(org_chart)
            ad_login = f"ad-synthetic-{index:03d}"
            await link_ad_account(
                session,
                identity.id,
                ad_login=ad_login,
                department=slot["department"],
                team=slot["team"],
                manager_ad_login=slot["manager_ad_login"],
            )
            print(f"{identity.display_label} ({identity.trueconf_subject}) -> {ad_login} / {slot['team']}")


if __name__ == "__main__":
    asyncio.run(main())
