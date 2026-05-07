"""labby-voice Teams agent."""

import logging

from microsoft_agents.hosting.core import TurnContext
from microsoft_agents.hosting.teams import TeamsActivityHandler

from bot.config import Config
from bot.tools.azure_resources import QUERIES, query_resources

logger = logging.getLogger(__name__)
config = Config()

# Set by app.py after initialization so the agent can initiate outbound calls
_call_handler = None


def set_call_handler(handler):
    global _call_handler
    _call_handler = handler


class LabbyVoiceAgent(TeamsActivityHandler):
    """Teams bot that can query Azure resources and handle voice interactions."""

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        text = (turn_context.activity.text or "").strip().lower()

        if text.startswith("#call"):
            await self._handle_call(turn_context, text)
        elif text.startswith("#resources"):
            await self._handle_resource_query(turn_context, text)
        elif text.startswith("#help"):
            await self._send_help(turn_context)
        else:
            await turn_context.send_activity(
                f"You said: {turn_context.activity.text}\n\nType `#help` to see available commands."
            )

    async def _handle_call(self, turn_context: TurnContext, text: str) -> None:
        """Prompt the user to start a voice session by calling the bot."""
        if not _call_handler:
            await turn_context.send_activity("Voice calling is not configured on this instance.")
            return

        await turn_context.send_activity(
            "📞 **To start a voice session:**\n\n"
            "Click the **phone icon** (🔊) at the top of this chat to call me directly.\n\n"
            "Once connected, you can talk to Labby about your Azure resources using natural speech."
        )

    async def _handle_resource_query(self, turn_context: TurnContext, text: str) -> None:
        parts = text.split(maxsplit=1)
        query_name = parts[1] if len(parts) > 1 else "all_resources"

        if query_name in QUERIES:
            kql = QUERIES[query_name]
        else:
            # Treat as a raw KQL query
            kql = query_name

        try:
            await turn_context.send_activity("Querying Azure resources...")
            results = await query_resources(
                query=kql,
                subscription_id=config.SUBSCRIPTION_ID,
                running_on_azure=config.RUNNING_ON_AZURE,
                client_id=config.CLIENT_ID or None,
            )

            if not results:
                await turn_context.send_activity("No resources found.")
                return

            # Format results as a simple table
            lines = []
            for row in results[:20]:  # Cap at 20 for readability
                lines.append(" | ".join(str(v) for v in row.values()))

            header = " | ".join(results[0].keys()) if results else ""
            response = f"**{header}**\n\n" + "\n".join(lines)

            if len(results) > 20:
                response += f"\n\n_...and {len(results) - 20} more resources_"

            await turn_context.send_activity(response)

        except Exception as e:
            logger.exception("Resource query failed")
            await turn_context.send_activity(f"Query failed: {e}")

    async def _send_help(self, turn_context: TurnContext) -> None:
        help_text = (
            "**Labby Voice Agent**\n\n"
            "Commands:\n"
            "- `#call` — Labby calls you on Teams for a voice conversation\n"
            "- `#resources` — List all Azure resources\n"
            "- `#resources vms` — List virtual machines\n"
            "- `#resources app_services` — List App Services\n"
            "- `#resources storage_accounts` — List storage accounts\n"
            "- `#resources aks_clusters` — List AKS clusters\n"
            "- `#resources resource_count_by_type` — Count by resource type\n"
            "- `#resources <KQL query>` — Run a custom Resource Graph query\n"
            "- `#help` — Show this help message"
        )
        await turn_context.send_activity(help_text)
