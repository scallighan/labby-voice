import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration loaded from environment variables.

    Env var names match the Container App config in terraform/main.tf.
    """

    # M365 Agent SDK connection settings
    TENANT_ID: str = os.getenv("TENANT_ID", "")
    CLIENT_ID: str = os.getenv("CLIENT_ID", "")
    RUNNING_ON_AZURE: bool = os.getenv("RUNNING_ON_AZURE", "") == "1"

    # Azure AI Foundry
    AI_PROJECT_ENDPOINT: str = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    FOUNDRY_MODEL: str = os.getenv("FOUNDRY_MODEL", "gpt-5.4-mini")

    # Azure AI Search
    SEARCH_ENDPOINT: str = os.getenv("AZURE_SEARCH_ENDPOINT", "")
    SEARCH_KNOWLEDGE_BASE_NAME: str = os.getenv("SEARCH_KNOWLEDGE_BASE_NAME", "")

    # Azure AI Speech (Voice Live API) — auth via Managed Identity, no key needed
    SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "eastus")

    # Azure Communication Services
    ACS_CONNECTION_STRING: str = os.getenv("ACS_CONNECTION_STRING", "")

    # Azure subscription for Resource Graph
    SUBSCRIPTION_ID: str = os.getenv("AZURE_SUBSCRIPTION_ID", "")

    # Server
    PORT: int = int(os.getenv("PORT", "3978"))
