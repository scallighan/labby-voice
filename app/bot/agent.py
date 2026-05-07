"""labby-voice Teams agent."""

import logging

import aiohttp
from azure.identity.aio import ClientSecretCredential, ManagedIdentityCredential
from microsoft_agents.hosting.core import TurnContext
from microsoft_agents.hosting.teams import TeamsActivityHandler

from bot.config import Config
from bot.tools.azure_resources import QUERIES, query_resources

logger = logging.getLogger(__name__)
config = Config()

# Set by app.py after initialization so the agent can initiate outbound calls
_call_handler = None

GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def set_call_handler(handler):
    global _call_handler
    _call_handler = handler


def _get_graph_credential():
    """Get credential for Microsoft Graph API calls."""
    if config.RUNNING_ON_AZURE and config.CLIENT_ID:
        return ManagedIdentityCredential(client_id=config.CLIENT_ID)
    import os

    client_secret = os.getenv("CLIENT_SECRET", "")
    if client_secret:
        return ClientSecretCredential(
            tenant_id=config.TENANT_ID,
            client_id=config.CLIENT_ID,
            client_secret=client_secret,
        )
    return None


async def _create_online_meeting(user_aad_id: str) -> dict | None:
    """Create a Teams online meeting via Microsoft Graph API.

    Uses application permissions (OnlineMeetings.ReadWrite.All) to create
    a meeting on behalf of the user.
    """
    credential = _get_graph_credential()
    if not credential:
        logger.error("No credential available for Graph API")
        return None

    try:
        token = await credential.get_token(GRAPH_SCOPE)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
        }
        body = {"subject": "Labby Voice Session"}

        async with aiohttp.ClientSession() as session:
            url = f"https://graph.microsoft.com/v1.0/users/{user_aad_id}/onlineMeetings"
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status == 201:
                    return await resp.json()
                error = await resp.text()
                logger.error("Graph API error creating meeting: %s %s", resp.status, error)
                return None
    finally:
        await credential.close()


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
        """Start a voice session by creating a Teams meeting, joining it, and sending the link."""
        if not _call_handler:
            await turn_context.send_activity("Voice calling is not configured on this instance.")
            return

        aad_id = getattr(turn_context.activity.from_property, "aad_object_id", None)
        if not aad_id:
            await turn_context.send_activity(
                "Could not resolve your Teams identity. Please ensure you're messaging from a Teams client."
            )
            return

        try:
            await turn_context.send_activity("🎙️ Setting up a voice session...")

            meeting = await _create_online_meeting(aad_id)
            if not meeting:
                await turn_context.send_activity("Failed to create meeting. Check Graph API permissions.")
                return

            join_url = meeting.get("joinWebUrl", "")

            # Bot joins the meeting via ACS Call Automation
            try:
                _call_handler.join_teams_meeting(join_url)
                logger.info("Bot joined meeting: %s", join_url)
            except Exception:
                logger.exception("Bot failed to join meeting")

            await turn_context.send_activity(
                f"📞 **Join the voice session:**\n\n[Click here to join]({join_url})\n\n"
                "Labby is already in the meeting — join and start talking about your Azure resources."
            )

        except Exception as e:
            logger.exception("Failed to set up voice session")
            await turn_context.send_activity(f"Failed to start voice session: {e}")

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
