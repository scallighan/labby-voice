"""ACS Call Automation handler for incoming Teams calls and meeting-based outbound calls."""

import json
import logging
import uuid

from azure.communication.callautomation import (
    AudioFormat,
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    StreamingTransportType,
)
from azure.communication.identity import CommunicationIdentityClient
from azure.core.rest import HttpRequest

logger = logging.getLogger(__name__)


class CallHandler:
    """Manages ACS Call Automation lifecycle: answer calls, join meetings, cleanup."""

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

    def _media_streaming_dict(self) -> dict:
        """Media streaming config as a dict for raw REST calls."""
        return {
            "transportUrl": self.media_streaming_url(),
            "transportType": "websocket",
            "contentType": "audio",
            "audioChannelType": "mixed",
            "startMediaStreaming": True,
            "enableBidirectional": True,
            "audioFormat": "Pcm16KMono",
        }

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

    def join_teams_meeting(self, teams_meeting_url: str) -> str:
        """Join a Teams meeting via its join URL using the ACS Call Automation REST API.

        The Python SDK doesn't expose teamsMeetingLinkLocator, so we send
        the createCall request directly with the meeting link in the body.

        Returns the call_connection_id for tracking.
        """
        api_version = self.client._client._config.api_version
        source_id = self._source_identity.properties["id"]
        body = {
            "targets": [
                {
                    "kind": "teamsMeeting",
                    "teamsMeetingLinkLocator": {"meetingLink": teams_meeting_url},
                }
            ],
            "source": {
                "kind": "communicationUser",
                "communicationUser": {"id": source_id},
                "id": source_id,
                "rawId": source_id,
            },
            "callbackUri": self.callback_url,
            "requestedModalities": ["audio"],
            "mediaStreamingOptions": self._media_streaming_dict(),
        }

        endpoint = self.client._client._config.endpoint.rstrip("/")
        request = HttpRequest(
            method="POST",
            url=f"{endpoint}/calling/callConnections?api-version={api_version}",
            headers={
                "Content-Type": "application/json",
                "Repeatability-Request-ID": str(uuid.uuid4()),
                "Repeatability-First-Sent": "Thu, 01 Jan 2026 00:00:00 GMT",
            },
            content=json.dumps(body),
        )

        response = self.client._client._client.send_request(request)
        response.raise_for_status()

        result = response.json()
        call_connection_id = result.get("callConnectionId", "unknown")
        logger.info("Joined Teams meeting, connection_id=%s", call_connection_id)
        return call_connection_id

    def hang_up(self, call_connection_id: str) -> None:
        """Hang up a call by connection ID."""
        try:
            call_conn = self.client.get_call_connection(call_connection_id)
            call_conn.hang_up(is_for_everyone=True)
            logger.info("Hung up call %s", call_connection_id)
        except Exception:
            logger.exception("Failed to hang up call %s", call_connection_id)
