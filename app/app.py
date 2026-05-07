"""labby-voice: aiohttp entrypoint for the Teams agent."""

import logging

from aiohttp import web
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter

from bot.agent import LabbyVoiceAgent, set_call_handler
from bot.config import Config
from call.handler import CallHandler
from call.media_stream import MediaBridge
from voice.handler import VoiceLiveHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = Config()
agent = LabbyVoiceAgent()

# Voice Live API handler (Speech service WebSocket)
voice_handler = VoiceLiveHandler(
    speech_region=config.SPEECH_REGION,
    running_on_azure=config.RUNNING_ON_AZURE,
    client_id=config.CLIENT_ID or None,
)

# ACS Call Automation + media bridge (initialized lazily if ACS is configured)
call_handler: CallHandler | None = None
media_bridge: MediaBridge | None = None

if config.ACS_CONNECTION_STRING and config.CALLBACK_BASE_URL:
    call_handler = CallHandler(
        acs_connection_string=config.ACS_CONNECTION_STRING,
        callback_base_url=config.CALLBACK_BASE_URL,
    )
    media_bridge = MediaBridge(voice_handler=voice_handler, config=config)
    set_call_handler(call_handler)
    logger.info("ACS Call Automation enabled")
else:
    logger.warning("ACS not configured — voice calling disabled (chat-only mode)")


def create_adapter() -> CloudAdapter:
    """Create CloudAdapter with MSAL auth configured from env vars."""
    auth_type = "UserManagedIdentity" if config.RUNNING_ON_AZURE else "ClientSecret"
    connection_manager = MsalConnectionManager(
        CONNECTIONS={
            "SERVICE_CONNECTION": {
                "SETTINGS": {
                    "AUTHTYPE": auth_type,
                    "CLIENTID": config.CLIENT_ID,
                    "TENANTID": config.TENANT_ID,
                }
            }
        }
    )
    return CloudAdapter(connection_manager=connection_manager)


adapter = create_adapter()


async def messages(request: web.Request) -> web.Response:
    response = await adapter.process(request, agent)
    return response or web.Response(status=200)


async def call_events(request: web.Request) -> web.Response:
    """Handle ACS Call Automation webhook events (incoming call, call connected, etc.)."""
    if not call_handler:
        return web.Response(status=501, text="Voice calling not configured")

    events = await request.json()
    if not isinstance(events, list):
        events = [events]

    for event in events:
        # Event Grid validation handshake
        if event.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            validation_code = event.get("data", {}).get("validationCode", "")
            logger.info("Event Grid validation handshake")
            return web.json_response({"validationResponse": validation_code})

        event_type = event.get("type", event.get("eventType", ""))
        event_data = event.get("data", {})
        logger.info("Call event: %s", event_type)

        if event_type in (
            "Microsoft.Communication.IncomingCall",
            "microsoft.communication.incomingcall",
        ):
            incoming_call_context = event_data.get("incomingCallContext", "")
            if incoming_call_context:
                try:
                    call_handler.answer_call(incoming_call_context)
                except Exception:
                    logger.exception("Failed to answer incoming call")

        elif "CallDisconnected" in event_type:
            call_connection_id = event_data.get("callConnectionId", "")
            if call_connection_id and media_bridge:
                await media_bridge._cleanup(call_connection_id)

        elif "CreateCallFailed" in event_type:
            logger.error("CreateCallFailed: %s", event_data)

    return web.Response(status=200)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def on_shutdown(app: web.Application) -> None:
    """Clean up active voice sessions on app shutdown."""
    if media_bridge:
        await media_bridge.cleanup_all()
    logger.info("Shutdown complete")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/messages", messages)
    app.router.add_post("/api/calls/events", call_events)
    app.router.add_get("/health", health)

    if media_bridge:
        app.router.add_get("/api/calls/media", media_bridge.handle_media_ws)

    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, port=config.PORT)
