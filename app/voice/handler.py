"""Voice Live API WebSocket handler for real-time voice interactions."""

import json
import logging
from dataclasses import dataclass, field

import websockets
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

logger = logging.getLogger(__name__)

SPEECH_SCOPE = "https://cognitiveservices.azure.com/.default"


def _get_credential(running_on_azure: bool, client_id: str | None = None):
    if running_on_azure and client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential()


@dataclass
class VoiceSession:
    """Tracks state for an active voice session."""

    session_id: str
    ws: websockets.WebSocketClientProtocol | None = None
    is_active: bool = False
    transcript_buffer: list[str] = field(default_factory=list)


class VoiceLiveHandler:
    """Manages WebSocket connections to the Azure Voice Live API.

    Handles bidirectional audio streaming between ACS and the Voice Live API
    for real-time speech-to-speech agent interactions.

    Authenticates via Azure AD token (Managed Identity or DefaultAzureCredential)
    instead of subscription keys.
    """

    def __init__(
        self,
        speech_region: str,
        running_on_azure: bool = False,
        client_id: str | None = None,
    ):
        self.speech_region = speech_region
        self._credential = _get_credential(running_on_azure, client_id)
        self.sessions: dict[str, VoiceSession] = {}

    @property
    def endpoint(self) -> str:
        return f"wss://{self.speech_region}.voice.speech.microsoft.com/api/v1/voice-live"

    def _get_auth_token(self) -> str:
        """Obtain a bearer token for the Speech service via Managed Identity."""
        token = self._credential.get_token(SPEECH_SCOPE)
        return token.token

    async def start_session(self, session_id: str) -> VoiceSession:
        """Open a WebSocket to Voice Live API and start a voice session."""
        session = VoiceSession(session_id=session_id)
        self.sessions[session_id] = session

        try:
            auth_token = self._get_auth_token()
            ws = await websockets.connect(
                self.endpoint,
                additional_headers={
                    "Authorization": f"Bearer {auth_token}",
                },
            )
            session.ws = ws
            session.is_active = True

            # Send session configuration
            await ws.send(
                json.dumps(
                    {
                        "type": "session.create",
                        "session": {
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm16",
                            "turn_detection": {
                                "type": "server_vad",
                            },
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "query_azure_resources",
                                        "description": "Query Azure resources using Azure Resource Graph (KQL)",
                                        "parameters": {
                                            "type": "object",
                                            "properties": {
                                                "query": {
                                                    "type": "string",
                                                    "description": (
                                                        "KQL query for Azure Resource Graph, "
                                                        "or a shortcut name like 'vms', 'all_resources'"
                                                    ),
                                                }
                                            },
                                            "required": ["query"],
                                        },
                                    },
                                }
                            ],
                            "instructions": (
                                "You are Labby, a helpful Azure infrastructure assistant. "
                                "You can query Azure resources to help users understand their cloud environment. "
                                "When users ask about their Azure resources, use the query_azure_resources tool. "
                                "Be concise and helpful in your responses."
                            ),
                        },
                    }
                )
            )

            logger.info("Voice session %s started", session_id)
            return session

        except Exception:
            logger.exception("Failed to start voice session %s", session_id)
            self.sessions.pop(session_id, None)
            raise

    async def send_audio(self, session_id: str, audio_data: bytes) -> None:
        """Send audio data to the Voice Live API."""
        session = self.sessions.get(session_id)
        if not session or not session.ws or not session.is_active:
            logger.warning("No active session %s for audio", session_id)
            return

        import base64

        await session.ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(audio_data).decode("utf-8"),
                }
            )
        )

    async def receive_events(self, session_id: str):
        """Async generator that yields events from the Voice Live API."""
        session = self.sessions.get(session_id)
        if not session or not session.ws:
            return

        try:
            async for message in session.ws:
                event = json.loads(message)
                event_type = event.get("type", "")

                if event_type == "session.created":
                    logger.info("Session %s confirmed by server", session_id)
                elif event_type == "response.audio.delta":
                    pass  # Audio chunk — yield to caller
                elif event_type == "response.function_call_arguments.done":
                    logger.info("Tool call received: %s", event.get("name"))
                elif event_type == "error":
                    logger.error("Voice API error: %s", event)

                yield event

        except websockets.ConnectionClosed:
            logger.info("Voice session %s connection closed", session_id)
        finally:
            session.is_active = False

    async def end_session(self, session_id: str) -> None:
        """Close a voice session."""
        session = self.sessions.pop(session_id, None)
        if session and session.ws:
            session.is_active = False
            await session.ws.close()
            logger.info("Voice session %s ended", session_id)

    async def handle_tool_call(self, session_id: str, event: dict, tool_executor) -> None:
        """Handle a function call from Voice Live API by executing the tool and sending results back."""
        session = self.sessions.get(session_id)
        if not session or not session.ws:
            return

        call_id = event.get("call_id", "")
        func_name = event.get("name", "")
        arguments = json.loads(event.get("arguments", "{}"))

        try:
            result = await tool_executor(func_name, arguments)
            await session.ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(result),
                        },
                    }
                )
            )
            # Trigger a new response after tool output
            await session.ws.send(json.dumps({"type": "response.create"}))
        except Exception:
            logger.exception("Tool call %s failed", func_name)
