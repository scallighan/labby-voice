# labby-voice

Voice-enabled Azure infrastructure assistant for Microsoft Teams.

## Architecture

```
Teams Call → ACS (audio bridge) → Voice Live API WebSocket → Python Agent
Teams Chat → M365 Agents SDK (aiohttp) → Python Agent
Python Agent → Azure Resource Graph → Azure Subscription Resources
```

The bot supports both **inbound** calls (user calls the bot in Teams) and **outbound** calls (bot calls the user via `/call` command). Voice audio is bridged through ACS Call Automation to the Azure Voice Live API for real-time speech-to-speech interactions.

- **app/**: Python agent using Microsoft 365 Agents SDK
  - `app.py` — entrypoint, creates aiohttp app with `/api/messages`, `/api/calls/events`, and `/health` routes
  - `bot/agent.py` — `LabbyVoiceAgent`, handles chat commands and outbound call initiation
  - `bot/tools/azure_resources.py` — Azure Resource Graph queries with KQL
  - `call/handler.py` — ACS Call Automation client for answering and creating calls
  - `call/media_stream.py` — Bidirectional audio bridge between ACS and Voice Live API
  - `voice/handler.py` — Voice Live API WebSocket client
- **terraform/**: Azure infrastructure (Bot Service, ACS, Speech, AI Foundry, Container App, RBAC)
- **appPackage/**: Teams app manifest with calling capability enabled

## Prerequisites

- Python 3.12+
- Azure subscription
- Terraform >= 1.5

## Setup

```bash
# Install Python dependencies
cd app
pip install -e ".[dev]"

# Copy and fill in environment variables
cp .env.example .env

# Deploy infrastructure
cd ../terraform
cp env.sample .env
source .env
terraform init
terraform apply
```

### Teams Interop (ACS ↔ Teams Federation)

The bot uses Azure Communication Services as an **external user** to call Teams users — no Teams Phone license is required. You must enable ACS-Teams federation on your tenant:

1. **Get your ACS immutable resource ID:**

   ```bash
   az communication show --name <acs-resource-name> --resource-group <rg-name> \
     --query "immutableResourceId" -o tsv
   ```

2. **Enable federation in Teams admin PowerShell:**

   ```powershell
   Connect-MicrosoftTeams

   Set-CsTeamsAcsFederationConfiguration `
     -Identity Global `
     -EnableAcsUsers $true `
     -AllowedAcsResources @("<acs-immutable-resource-id>")
   ```

3. **Verify federation is enabled:**

   ```powershell
   Get-CsTeamsAcsFederationConfiguration
   ```

> **Note:** This federation setup allows ACS to place VoIP calls to Teams users as an external caller. No Teams Phone or Enterprise Voice license is needed on the Teams user side.

## Development

```bash
# Run the agent locally
cd app
python app.py

# Lint
ruff check .

# Format
ruff format .
```

## Teams Commands

- `/call` — Labby calls you on Teams for a voice conversation
- `/resources` — List all Azure resources
- `/resources vms` — List virtual machines
- `/resources <KQL>` — Run a custom Resource Graph query
- `/help` — Show available commands