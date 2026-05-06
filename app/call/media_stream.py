"""Bidirectional media bridge between ACS media streaming and Voice Live API."""

import asyncio
import base64
import json
import logging

from aiohttp import web

from bot.config import Config
from bot.tools.azure_resources import query_resources
from voice.handler import VoiceLiveHandler

logger = logging.getLogger(__name__)


class MediaBridge:
    """Bridges audio between an ACS media streaming WebSocket and the Voice Live API.

    For each active call, two async tasks run concurrently:
      - ACS → Voice Live: receives audio from ACS, forwards PCM16 to Voice Live API
      - Voice Live → ACS: receives events/audio from Voice Live API, forwards back to ACS
    """

    def __init__(self, voice_handler: VoiceLiveHandler, config: Config):
        self.voice_handler = voice_handler
        self.config = config
        # call_connection_id → running pump task
        self._tasks: dict[str, asyncio.Task] = {}

    async def handle_media_ws(self, request: web.Request) -> web.WebSocketResponse:
        """aiohttp WebSocket handler for ACS media streaming at /api/calls/media."""
        acs_ws = web.WebSocketResponse()
        await acs_ws.prepare(request)

        call_connection_id: str | None = None
        logger.info("ACS media WebSocket connected")

        try:
            async for msg in acs_ws:
                if msg.type != web.WSMsgType.TEXT:
                    continue

                data = json.loads(msg.data)
                kind = data.get("kind")

                if kind == "AudioMetadata":
                    metadata = data.get("audioMetadata", {})
                    call_connection_id = metadata.get("callConnectionId", "unknown")
                    logger.info(
                        "ACS media metadata: connection=%s encoding=%s rate=%s",
                        call_connection_id,
                        metadata.get("encoding"),
                        metadata.get("sampleRate"),
                    )
                    # Start Voice Live session and the outbound audio pump
                    task = asyncio.create_task(
                        self._run_voice_to_acs_pump(call_connection_id, acs_ws),
                        name=f"voice-pump-{call_connection_id}",
                    )
                    self._tasks[call_connection_id] = task

                elif kind == "AudioData":
                    audio_data = data.get("audioData", {})
                    raw_audio = audio_data.get("data", "")
                    if raw_audio and call_connection_id:
                        pcm_bytes = base64.b64decode(raw_audio)
                        await self.voice_handler.send_audio(call_connection_id, pcm_bytes)

                elif kind == "StoppedMediaStreaming":
                    logger.info("ACS media streaming stopped for %s", call_connection_id)
                    break

        except Exception:
            logger.exception("ACS media WebSocket error")
        finally:
            await self._cleanup(call_connection_id)

        return acs_ws

    async def _run_voice_to_acs_pump(self, call_connection_id: str, acs_ws: web.WebSocketResponse) -> None:
        """Receive events from Voice Live API and forward audio back to ACS."""
        try:
            session = await self.voice_handler.start_session(call_connection_id)
            if not session:
                logger.error("Failed to start Voice Live session for %s", call_connection_id)
                return

            async for event in self.voice_handler.receive_events(call_connection_id):
                event_type = event.get("type", "")

                if event_type == "response.audio.delta":
                    audio_b64 = event.get("delta", "")
                    if audio_b64 and not acs_ws.closed:
                        await acs_ws.send_json(
                            {
                                "kind": "AudioData",
                                "audioData": {
                                    "data": audio_b64,
                                },
                            }
                        )

                elif event_type == "response.function_call_arguments.done":
                    await self.voice_handler.handle_tool_call(
                        call_connection_id,
                        event,
                        self._execute_tool,
                    )

                elif event_type == "error":
                    logger.error("Voice Live API error for %s: %s", call_connection_id, event)

        except Exception:
            logger.exception("Voice-to-ACS pump error for %s", call_connection_id)

    async def _execute_tool(self, func_name: str, arguments: dict) -> dict:
        """Execute a tool call from the Voice Live API."""
        if func_name == "query_azure_resources":
            query = arguments.get("query", "all_resources")
            results = await query_resources(
                query=query,
                subscription_id=self.config.SUBSCRIPTION_ID,
                running_on_azure=self.config.RUNNING_ON_AZURE,
                client_id=self.config.CLIENT_ID or None,
            )
            return {"resources": results[:20], "total": len(results)}

        return {"error": f"Unknown tool: {func_name}"}

    async def _cleanup(self, call_connection_id: str | None) -> None:
        """Clean up Voice Live session and pump tasks for a call."""
        if not call_connection_id:
            return

        task = self._tasks.pop(call_connection_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self.voice_handler.end_session(call_connection_id)
        logger.info("Cleaned up media bridge for %s", call_connection_id)

    async def cleanup_all(self) -> None:
        """Shut down all active sessions. Called on app shutdown."""
        for cid in list(self._tasks.keys()):
            await self._cleanup(cid)
