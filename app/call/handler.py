"""ACS Call Automation handler for incoming Teams calls and meeting-based outbound calls."""

import logging

from azure.communication.callautomation import (
    AudioFormat,
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    StreamingTransportType,
)
from azure.communication.identity import CommunicationIdentityClient

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

    def join_teams_meeting(self, meeting_url: str) -> str:
        """Join a Teams meeting by URL using raw bytes through the generated createCall endpoint.

        The Python SDK doesn't have a typed model for Teams meeting links, so we
        pass raw JSON bytes to the generated client's create_call method (which
        accepts IO[bytes]). This uses the SDK's auth pipeline and URL construction.

        Returns the call_connection_id for tracking.
        """
        source_id = self._source_identity.properties["id"]
        body = {
            "targets": [
                {
                    "id": source_id,
                    "rawId": source_id,
                    "kind": "communicationUser",
                    "communicationUser": {"id": source_id},
                }
            ],
            "source": {
                "id": source_id,
                "rawId": source_id,
                "kind": "communicationUser",
                "communicationUser": {"id": source_id},
            },
            "callbackUri": self.callback_url,
            "mediaStreamingOptions": self._media_streaming_dict(),
            "callLocator": {
                "kind": "teamsMeetingLinkLocator",
                "meetingLink": meeting_url,
            },
        }

        logger.info("createCall with meeting link: %s", meeting_url)
        # Bypass isinstance check by passing as a dict — SDK will try to serialize
        # it as a model and fail. Instead, use the internal pipeline directly.
        from azure.communication.callautomation._generated.operations._operations import (
            build_azure_communication_call_automation_service_create_call_request,
        )

        _request = build_azure_communication_call_automation_service_create_call_request(
            content_type="application/json",
            api_version=self.client._client._config.api_version,
            json=body,
        )
        path_format_arguments = {
            "endpoint": self.client._client._serialize.url(
                "self._config.endpoint", self.client._client._config.endpoint, "str", skip_quote=True
            ),
        }
        _request.url = self.client._client._client.format_url(_request.url, **path_format_arguments)

        pipeline_response = self.client._client._client._pipeline.run(_request, stream=False)
        response = pipeline_response.http_response

        if response.status_code not in [201]:
            from azure.core.exceptions import HttpResponseError

            raise HttpResponseError(response=response)

        result = self.client._client._deserialize("CallConnectionProperties", pipeline_response.http_response)

        call_connection_id = result.call_connection_id
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
