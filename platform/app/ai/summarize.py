"""Turn one alert into the sentence a human actually reads in TrueConf.

The simplest useful AI usage in this system: one short, JSON-constrained
call to the local Qwen model asking for a headline, a priority, and a next
step. No history, no tools, no chain of anything.

Two rules govern this module, both inherited from app/ai/service.py:

- **It never raises, and never blocks delivery.** Every failure path --
  model down, timeout, garbage JSON, priority outside the vocabulary --
  falls back to `heuristic_summary()`, which is pure string formatting over
  fields the alert already has. A notification always gets sent; the model
  only decides how well it reads.
- **It does not open a second way to call an LLM.** app/ai/client.py stays
  the only HTTP-to-model seam in the codebase.

`source` on the result records which path produced it, so "how often is the
model actually contributing" is answerable from the notification payload
rather than from log archaeology.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from app.ai.client import AIClientError, LLMClient
from app.ai.service import PRIORITIES
from app.contracts.messages import MonitoringAlert

logger = logging.getLogger(__name__)

DEFAULT_SUMMARY_TIMEOUT_SECONDS = 10.0
MAX_HEADLINE_CHARS = 160
MAX_NEXT_STEP_CHARS = 200

# Severity -> priority when the model is unavailable or unusable. Mirrors the
# ordering in app/core/correlation_automaton.py's SEVERITY_RANK; anything
# unrecognised lands on p3 rather than erroring, the same "one odd vendor
# label must not take a signal out of service" rule that module applies.
_HEURISTIC_PRIORITY = {
    "critical": "p1",
    "high": "p2",
    "average": "p3",
    "warning": "p3",
    "info": "p4",
    "resolved": "p4",
}
_DEFAULT_PRIORITY = "p3"

_SYSTEM_PROMPT = f"""You write one-line incident notifications for on-call engineers.
Reply with a single JSON object and nothing else. Keys:
- "headline": one sentence, max 20 words, naming what is wrong and where. No pleasantries.
- "priority": one of {list(PRIORITIES)} (p1 = wake someone now, p4 = informational)
- "next_step": one short imperative sentence telling the engineer what to check first.
Be concrete and factual. Do not invent causes the data does not support."""


@dataclass(frozen=True)
class Summary:
    headline: str
    priority: str
    next_step: str
    source: Literal["model", "heuristic"]


def heuristic_summary(alert: MonitoringAlert, reason: str = "") -> Summary:
    """Deterministic fallback. Never fails, never calls anything."""
    service = alert.labels.get("service") or alert.source
    priority = _HEURISTIC_PRIORITY.get(alert.severity.lower(), _DEFAULT_PRIORITY)
    headline = (
        f"{alert.severity.upper()}: {alert.rule} on {service} "
        f"({alert.metric} = {alert.value:g}, threshold {alert.threshold:g})"
    )
    next_step = f"Check {alert.metric} on {alert.source}."
    if reason:
        next_step = f"{next_step} Correlation: {reason}"
    return Summary(
        headline=headline[:MAX_HEADLINE_CHARS],
        priority=priority,
        next_step=next_step[:MAX_NEXT_STEP_CHARS],
        source="heuristic",
    )


def build_messages(alert: MonitoringAlert, reason: str) -> list[dict]:
    """Module-level and pure so tests can assert on the prompt without a
    live model, matching app/ai/service.py's build_messages."""
    labels = ", ".join(f"{k}={v}" for k, v in sorted(alert.labels.items())) or "none"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"rule: {alert.rule}\n"
                f"severity: {alert.severity}\n"
                f"host: {alert.source}\n"
                f"metric: {alert.metric} = {alert.value} (threshold {alert.threshold})\n"
                f"labels: {labels}\n"
                f"why this fired now: {reason or 'first alert for this correlation key'}"
            ),
        },
    ]


def _text(raw: object, limit: int) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()[:limit]


class NotificationSummarizer:
    """One instance per process. The client is injectable so tests exercise
    the parsing and fallback logic with no HTTP."""

    def __init__(
        self,
        client: LLMClient | None = None,
        timeout_seconds: float = DEFAULT_SUMMARY_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client or LLMClient()
        self._timeout = timeout_seconds

    async def summarize(self, alert: MonitoringAlert, reason: str = "") -> Summary:
        fallback = heuristic_summary(alert, reason)
        try:
            reply, _model = await asyncio.wait_for(
                self._client.chat_json(build_messages(alert, reason), max_tokens=200),
                timeout=self._timeout,
            )
        except (AIClientError, TimeoutError, asyncio.CancelledError):
            return fallback
        except Exception:
            # chat_json is contract-bound to raise only AIClientError, so
            # anything else is a bug rather than an outage. Still degrade to
            # the heuristic -- a notification that reads plainly beats one
            # that never arrives -- but log it loudly instead of silently.
            logger.exception("Notification summarizer failed unexpectedly for alert %s", alert.alert_id)
            return fallback

        headline = _text(reply.get("headline"), MAX_HEADLINE_CHARS)
        next_step = _text(reply.get("next_step"), MAX_NEXT_STEP_CHARS)
        priority = _text(reply.get("priority"), 8)
        if priority is not None:
            priority = priority.lower()
        # Partial credit: keep whichever fields the model got right and take
        # the rest from the heuristic, rather than discarding a good headline
        # because the priority was out of vocabulary.
        return Summary(
            headline=headline or fallback.headline,
            priority=priority if priority in PRIORITIES else fallback.priority,
            next_step=next_step or fallback.next_step,
            source="model" if headline else "heuristic",
        )
