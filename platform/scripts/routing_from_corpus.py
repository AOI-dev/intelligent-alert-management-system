"""Generate platform/routing.json from a scenario corpus's CMDB block.

    cd platform && python3 -m scripts.routing_from_corpus ../scenario/corpus.json routing.json

The corpus already declares services, owning teams, engineers and their
contact channels, and scenario/cascade.pl's validate/0 refuses to emit one
where those disagree. Deriving routing config from it means the demo path
cannot drift from the corpus the filter is scored against.

One thing is deliberately NOT carried over: the corpus rota. Its shifts are
offsets in seconds from corpus start (a 2-hour window), which has no meaning
as a wall-clock schedule. The generator picks each team's first engineer as
`oncall` and leaves `shifts` for a human to write in UTC HH:MM -- see
routing.example.json. The corpus rota exists to score per-user precision,
not to run a real pager.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_WEBHOOK = "http://161.104.107.172:8120/v1/notify"


def build_routing(corpus: dict, webhook_url: str) -> dict:
    cmdb = corpus["cmdb"]
    services = {service["id"]: service["owner_team"] for service in cmdb["services"]}

    teams: dict[str, dict] = {}
    for shift in cmdb.get("on_call", []):
        # First shift listed for a team wins; ordering is stable because the
        # corpus is generated deterministically.
        teams.setdefault(shift["team"], {"oncall": shift["login"]})
    for service in cmdb["services"]:
        teams.setdefault(service["owner_team"], {})

    targets: dict[str, dict] = {}
    for user in cmdb["users"]:
        contacts = {contact["channel"]: contact["address"] for contact in user.get("contacts", [])}
        trueconf_id = contacts.get("trueconf")
        if trueconf_id is None:
            # Managers are escalation contacts on email only; they are not
            # pager targets, so leaving them out is correct rather than a gap.
            continue
        targets[user["login"]] = {"trueconf_id": trueconf_id, "webhook_url": webhook_url}

    # A team whose on-call has no TrueConf contact would resolve to a target
    # that does not exist, and the alert would be silently dropped at routing
    # time. Fail here instead.
    for team, entry in teams.items():
        oncall = entry.get("oncall")
        if oncall and oncall not in targets:
            raise SystemExit(f"team {team!r} on-call {oncall!r} has no trueconf contact in the corpus CMDB")

    default_team = next(iter(sorted(teams)), None)
    return {
        "default_team": default_team,
        "services": services,
        "teams": teams,
        "targets": targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="corpus.json from scenario/cascade.pl")
    parser.add_argument("out", type=Path, nargs="?", default=Path("routing.json"))
    parser.add_argument("--webhook-url", default=DEFAULT_WEBHOOK, help=f"default: {DEFAULT_WEBHOOK}")
    args = parser.parse_args()

    with args.corpus.open() as handle:
        corpus = json.load(handle)

    routing = build_routing(corpus, args.webhook_url)
    with args.out.open("w") as handle:
        json.dump(routing, handle, indent=2)
        handle.write("\n")

    print(
        f"wrote {args.out}: {len(routing['services'])} services, "
        f"{len(routing['teams'])} teams, {len(routing['targets'])} targets"
    )
    print("NOTE: `shifts` are not generated -- add them in UTC HH:MM if you need a rota.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
