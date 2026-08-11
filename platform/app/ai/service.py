"""AI enrichment service: turns an EnrichmentRequest into EnrichmentResults
by calling the LLM client (app/ai/client.py) once per request and parsing
out each requested capability.

Contract with the rest of the platform (and what tests/ai/ pins):

- enrich() NEVER raises. A model outage, a garbage reply, or an
  out-of-vocabulary answer all produce a valid fallback EnrichmentResult
  (confidence 0.0, explanation naming the failure) instead — the same
  "must not block or break the deterministic path" principle applied to
  plugins in app/plugins/engine.py and to the TimescaleDB projection.
- A result always satisfies the EnrichmentResult contract, including
  confidence within [0, 1], whatever the model actually said.
- recommendation, when the model gives one, is constrained to the
  capability's declared vocabulary below; anything else is discarded
  (kept in the explanation) rather than passed upstream as if trusted.
"""
import logging

from app.ai.client import AIClientError, LLMClient
from app.contracts.messages import EnrichmentRequest, EnrichmentResult

logger = logging.getLogger(__name__)

# What each capability may recommend. The oracle in tests/ai/oracle.py
# references these same vocabularies; keep them the single source here.
CLASSIFICATIONS = (
    "infrastructure",
    "network",
    "database",
    "application",
    "security",
    "unknown",
)
PRIORITIES = ("p1", "p2", "p3", "p4")

_FALLBACK_EXPLANATION = "enrichment unavailable: model call failed"

_SYSTEM_PROMPT = f"""You are part of an alert-management platform. You enrich one monitoring \
alert at a time. Reply with a single JSON object and nothing else. Keys:
- "classification": one of {list(CLASSIFICATIONS)}
- "priority": one of {list(PRIORITIES)} (p1 = page someone now, p4 = informational)
- "root_cause": short free-text hypothesis, or null if you have none
- "confidence": float 0..1, your overall confidence
- "explanation": one or two sentences justifying the above
Omit any key you were not asked for."""


def _alert_text(request: EnrichmentRequest) -> str:
    alert = request.alert
    labels = ", ".join(f"{k}={v}" for k, v in sorted(alert.labels.items())) or "none"
    return (
        f"rule: {alert.rule}\n"
        f"severity: {alert.severity}\n"
        f"source: {alert.source}\n"
        f"metric: {alert.metric} = {alert.value} (threshold {alert.threshold})\n"
        f"labels: {labels}"
    )


def build_messages(request: EnrichmentRequest) -> list[dict]:
    """The prompt for one enrichment request. Module-level and pure so tests
    can assert on it without a live model."""
    capabilities = ", ".join(request.requested_capabilities)
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Enrich this alert. Requested capabilities: {capabilities}.\n\n"
            f"{_alert_text(request)}",
        },
    ]


def _clamp_confidence(raw: object) -> float:
    """Contract guarantee: confidence is always a float in [0, 1], whatever
    the model returned."""
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def _recommendation(capability: str, reply: dict) -> str | None:
    raw = reply.get(capability)
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip().lower()
    if capability == "classification":
        return value if value in CLASSIFICATIONS else None
    if capability == "priority":
        return value if value in PRIORITIES else None
    # root_cause is free text; cap it so a verbose model can't bloat the
    # result message.
    return value[:200]


class EnrichmentService:
    """One instance per process. The LLM client is injectable so unit tests
    exercise this parsing/fallback logic without any HTTP."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client or LLMClient()

    def _fallback(self, request: EnrichmentRequest, reason: str) -> list[EnrichmentResult]:
        return [
            EnrichmentResult(
                alert_id=request.alert.alert_id,
                capability=capability,
                confidence=0.0,
                explanation=reason,
                model_name="unavailable",
                model_version="0",
            )
            for capability in request.requested_capabilities
        ]

    async def enrich(self, request: EnrichmentRequest) -> list[EnrichmentResult]:
        try:
            reply, model_id = await self._client.chat_json(build_messages(request))
        except AIClientError as exc:
            logger.warning("enrichment model call failed for alert %s: %s", request.alert.alert_id, exc)
            return self._fallback(request, _FALLBACK_EXPLANATION)

        confidence = _clamp_confidence(reply.get("confidence", 0.0))
        explanation = str(reply.get("explanation") or "model returned no explanation")
        results = []
        for capability in request.requested_capabilities:
            recommendation = _recommendation(capability, reply)
            if recommendation is None and capability != "root_cause":
                explanation_for = (
                    f"{explanation} (note: model's {capability} answer was missing or "
                    "outside the declared vocabulary and was discarded)"
                )
            else:
                explanation_for = explanation
            results.append(
                EnrichmentResult(
                    alert_id=request.alert.alert_id,
                    capability=capability,
                    confidence=confidence,
                    explanation=explanation_for,
                    model_name=model_id,
                    model_version=model_id,
                    recommendation=recommendation,
                )
            )
        return results
