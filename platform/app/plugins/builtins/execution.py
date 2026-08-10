"""Built-in decision executor: logs decisions, used as a no-op default."""

import logging
from collections.abc import Mapping
from typing import Any

from app.contracts.messages import Decision
from app.plugins.ports import DecisionExecutor, PluginMetadata

logger = logging.getLogger(__name__)


class LoggingExecutor:
    """Default executor that logs decisions instead of acting on them.

    Replace with real implementations (PagerDuty, Slack, Zabbix suppress,
    TrueConf bridge, Jira, etc.) by listing them in PLUGIN_PATHS.
    """

    metadata = PluginMetadata(
        name="logging-executor",
        version="0.1.0",
        category="execution",
        description="Logs every decision; safe no-op default.",
    )

    async def can_execute(self, decision: Decision) -> bool:
        return True

    async def execute(self, decision: Decision, context: Mapping[str, Any]) -> None:
        logger.info("Decision %s for %s", decision.decision_type, decision.alert_id)
