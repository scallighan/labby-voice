"""ACS Call Automation handler for incoming Teams calls."""

import logging

from azure.communication.callautomation import (
    AudioFormat,
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    StreamingTransportType,
)

logger = logging.getLogger(__name__)


class CallHandler:
    """Manages ACS Call Automation lifecycle: answer calls, handle events, cleanup."""

    def __init__(self, acs_connection_string: str, callback_base_url: str):
        self.client = CallAutomationClient.from_connection_string(acs_connection_string)
        self.callback_base_url = callback_base_url.rstrip("/")

    @property
    def callback_url(self) -> str:
        return f"{self.callback_base_url}/api/calls/events"

    def media_streaming_url(self) -> str:
        base = self.callback_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/api/calls/media"

    def answer_call(self, incoming_call_context: str) -> str:
        """Answer an incoming call with bidirectional media streaming enabled.

        Returns the call_connection_id for tracking.
        """
        media_streaming = MediaStreamingOptions(
            transport_url=self.media_streaming_url(),
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM16_K_MONO,
        )

        result = self.client.answer_call(
            incoming_call_context=incoming_call_context,
            callback_url=self.callback_url,
            media_streaming=media_streaming,
        )

        call_connection_id = result.call_connection.call_connection_id
        logger.info("Answered call, connection_id=%s", call_connection_id)
        return call_connection_id

    def hang_up(self, call_connection_id: str) -> None:
        """Hang up a call by connection ID."""
        try:
            call_conn = self.client.get_call_connection(call_connection_id)
            call_conn.hang_up(is_for_everyone=True)
            logger.info("Hung up call %s", call_connection_id)
        except Exception:
            logger.exception("Failed to hang up call %s", call_connection_id)
