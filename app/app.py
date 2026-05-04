"""labby-voice: aiohttp entrypoint for the Teams agent."""

import logging

from aiohttp import web
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter

from bot.agent import LabbyVoiceAgent
from bot.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = Config()
agent = LabbyVoiceAgent()


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


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/health", health)
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, port=config.PORT)
