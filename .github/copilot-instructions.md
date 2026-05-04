# Copilot Instructions for labby-voice

## Overview

Voice-enabled Azure infrastructure assistant for Microsoft Teams. Uses M365 Agents SDK (Python) with Azure Communication Services + Voice Live API for real-time voice, and Azure Resource Graph for querying Azure resources.

## Architecture

```
Teams Call → ACS (audio bridge) → Voice Live API WebSocket → Python Agent
Teams Chat → M365 Agents SDK (aiohttp) → Python Agent
Python Agent → Azure Resource Graph → Azure Subscription Resources
```

- **app/**: Python agent (aiohttp + M365 Agents SDK)
  - `app.py` — entrypoint, creates aiohttp app with `/api/messages` and `/health` routes
  - `bot/agent.py` — `LabbyVoiceAgent` subclasses `TeamsActivityHandler`
  - `bot/tools/azure_resources.py` — Azure Resource Graph queries with KQL
  - `voice/handler.py` — Voice Live API WebSocket client for bidirectional audio
  - `bot/config.py` — centralized config from env vars (matches Container App env in Terraform)
- **terraform/**: All Azure infrastructure (Bot Service, ACS, Speech, AI Foundry, Container App, RBAC)
- **appPackage/**: Teams app manifest with calling capability enabled

## Commands

```bash
# Install deps
cd app && pip install -e ".[dev]"

# Run locally
cd app && python app.py

# Lint + format
cd app && ruff check . && ruff format .

# Terraform
cd terraform && terraform init && terraform plan
```

## Conventions

- Python 3.12+, uses `pyproject.toml` (not requirements.txt)
- Formatting/linting: `ruff` (line length 120, rules: E, F, I, W)
- Auth: User Assigned Managed Identity (not secrets) — see `terraform/main.tf`
- Env vars in `bot/config.py` must match Container App env blocks in `terraform/main.tf`
- Never commit `.tfvars`, `.tfstate`, or `.env` files
- Container images published to `ghcr.io`
- Terraform naming: resources use `local.func_name` suffix pattern
