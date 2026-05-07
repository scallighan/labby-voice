"""ACS Call Automation handler for incoming Teams calls."""

import logging

from azure.communication.callautomation import (
    AudioFormat,
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    MicrosoftTeamsUserIdentifier,
    StreamingTransportType,
)
from azure.communication.identity import CommunicationIdentityClient

logger = logging.getLogger(__name__)


class CallHandler:
    """Manages ACS Call Automation lifecycle: answer calls, handle events, cleanup."""

    def __init__(self, acs_connection_string: str, callback_base_url: str):
        self.identity_client = CommunicationIdentityClient.from_connection_string(acs_connection_string)
        # Create a persistent ACS identity to use as the call source
        self._source_identity = self.identity_client.create_user()
        self.client = CallAutomationClient.from_connection_string(acs_connection_string, source=self._source_identity)
        self.callback_base_url = callback_base_url.rstrip("/")
        logger.info("CallHandler initialized with source identity: %s", self._source_identity.properties["id"])

    @property
    def callback_url(self) -> str:
        return f"{self.callback_base_url}/api/calls/events"

    def media_streaming_url(self) -> str:
        base = self.callback_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/api/calls/media"

    def _media_streaming_options(self) -> MediaStreamingOptions:
        """Build reusable media streaming config for bidirectional audio."""
        return MediaStreamingOptions(
            transport_url=self.media_streaming_url(),
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM16_K_MONO,
        )

    def answer_call(self, incoming_call_context: str) -> str:
        """Answer an incoming call with bidirectional media streaming enabled.

        Returns the call_connection_id for tracking.
        """
        result = self.client.answer_call(
            incoming_call_context=incoming_call_context,
            callback_url=self.callback_url,
            media_streaming=self._media_streaming_options(),
        )

        call_connection_id = result.call_connection_id
        logger.info("Answered call, connection_id=%s", call_connection_id)
        return call_connection_id

    def create_call(self, teams_user_aad_id: str, display_name: str = "Labby Voice") -> str:
        """Initiate an outbound call to a Teams user via ACS as a CommunicationUser.

        Creates a temporary ACS identity to act as the caller, then places
        the call to the target Teams user.

        Args:
            teams_user_aad_id: The target user's Microsoft Entra (AAD) Object ID.
            display_name: Caller display name shown to the Teams user.

        Returns the call_connection_id for tracking.
        """
        target = MicrosoftTeamsUserIdentifier(user_id=teams_user_aad_id)

        result = self.client.create_call(
            target_participant=target,
            callback_url=self.callback_url,
            source_display_name=display_name,
            media_streaming=self._media_streaming_options(),
        )

        call_connection_id = result.call_connection_id
        logger.info("Outbound call to %s, connection_id=%s", teams_user_aad_id, call_connection_id)
        return call_connection_id

    def hang_up(self, call_connection_id: str) -> None:
        """Hang up a call by connection ID."""
        try:
            call_conn = self.client.get_call_connection(call_connection_id)
            call_conn.hang_up(is_for_everyone=True)
            logger.info("Hung up call %s", call_connection_id)
        except Exception:
            logger.exception("Failed to hang up call %s", call_connection_id)
