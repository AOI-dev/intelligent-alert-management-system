"""File-backed routing registry: which human a service's alerts belong to,
and how to reach them.

notifications/README.md describes this gap directly -- the dispatcher needs
`webhook_url` already resolved by whoever publishes the request, because no
target registry exists. This is that registry, deliberately file-backed
rather than a database table: routing config is small, reviewable, and
belongs in Git next to the stack it routes for, the same argument flags.env
already makes.

Config shape (see platform/routing.example.json):

    {
      "services": { "<service>": "<team>" },
      "teams":    { "<team>": { "oncall": "<login>", "shifts": [...] } },
      "targets":  { "<login>": { "trueconf_id": "...", "webhook_url": "..." } },
      "default_team": "<team>"
    }

`shifts` is optional; when present it overrides `oncall` for the matching
window, so a rota can be expressed without a scheduler. Absent config is a
valid state -- resolve() returns None and the caller sends nothing, rather
than the pipeline failing over a missing file.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Target:
    """A resolved notification recipient."""

    target_id: str
    trueconf_id: str
    webhook_url: str
    team: str


def _parse_hhmm(value: str) -> time | None:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour=hour, minute=minute)
    except (AttributeError, TypeError, ValueError):
        return None


class RoutingRegistry:
    """Resolves service -> team -> on-call login -> contact details.

    Immutable once loaded. Reload by constructing a new instance; the config
    is small enough that in-place mutation buys nothing and would make the
    resolution racy against in-flight alerts.
    """

    def __init__(self, config: dict) -> None:
        self._services: dict[str, str] = dict(config.get("services", {}))
        self._teams: dict[str, dict] = dict(config.get("teams", {}))
        self._targets: dict[str, dict] = dict(config.get("targets", {}))
        self._default_team: str | None = config.get("default_team")

    @classmethod
    def from_file(cls, path: str | Path) -> "RoutingRegistry":
        """Load config, or return an empty registry if it is missing or
        malformed. A routing misconfiguration must not stop alert
        processing -- it degrades to "nobody is notified", which is visible
        in the logs and in the notification metrics, rather than taking
        ingestion down."""
        location = Path(path)
        if not location.is_file():
            logger.warning("Routing config %s not found; no notifications will be routed", location)
            return cls({})
        try:
            with location.open() as handle:
                return cls(json.load(handle))
        except (OSError, ValueError):
            logger.exception("Routing config %s is unreadable; no notifications will be routed", location)
            return cls({})

    @property
    def configured(self) -> bool:
        return bool(self._targets)

    def team_for(self, service: str | None) -> str | None:
        if service and service in self._services:
            return self._services[service]
        return self._default_team

    def _on_call_login(self, team: str, at: datetime) -> str | None:
        entry = self._teams.get(team)
        if entry is None:
            return None
        moment = at.astimezone(timezone.utc).time()
        for shift in entry.get("shifts", []):
            start = _parse_hhmm(shift.get("from", ""))
            end = _parse_hhmm(shift.get("to", ""))
            login = shift.get("login")
            if start is None or end is None or not login:
                continue
            # A shift crossing midnight (22:00->06:00) is two ranges, not one
            # comparison -- getting this wrong would silently drop the night
            # shift, which is when an unrouted page hurts most.
            within = start <= moment < end if start < end else (moment >= start or moment < end)
            if within:
                return login
        return entry.get("oncall")

    def resolve(self, service: str | None, at: datetime | None = None) -> Target | None:
        """The person to notify for an alert on `service` at time `at`."""
        team = self.team_for(service)
        if team is None:
            return None
        login = self._on_call_login(team, at or datetime.now(timezone.utc))
        if login is None:
            return None
        contact = self._targets.get(login)
        if contact is None:
            logger.warning("Routing: on-call login %r for team %r has no target entry", login, team)
            return None
        webhook_url = contact.get("webhook_url")
        if not webhook_url:
            logger.warning("Routing: target %r has no webhook_url", login)
            return None
        return Target(
            target_id=login,
            trueconf_id=contact.get("trueconf_id", login),
            webhook_url=webhook_url,
            team=team,
        )
