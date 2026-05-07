# labby-voice

Voice-enabled Azure infrastructure assistant for Microsoft Teams.

## Architecture

```
Teams Chat → M365 Agents SDK (aiohttp) → Python Agent
#call → Graph API (create meeting) → ACS connect_call (join) → MediaBridge → Voice Live API
Python Agent → Azure Resource Graph → Azure Subscription Resources
```

The bot supports voice sessions via the `#call` command: the bot creates a Teams online meeting via the Microsoft Graph API, joins it via ACS Call Automation (`connect_call` with the meeting's thread ID), and sends the user a join link. Voice audio is bridged through ACS to the Azure Voice Live API for real-time speech-to-speech interactions.

- **app/**: Python agent using Microsoft 365 Agents SDK
  - `app.py` — entrypoint, creates aiohttp app with `/api/messages`, `/api/calls/events`, and `/health` routes
  - `bot/agent.py` — `LabbyVoiceAgent`, handles chat commands and meeting-based voice sessions
  - `bot/tools/azure_resources.py` — Azure Resource Graph queries with KQL
  - `call/handler.py` — ACS Call Automation client for answering calls and joining meetings
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

### Teams Admin Configuration

The bot requires two Teams admin PowerShell configurations. Install the module first if needed:

```powershell
Install-Module MicrosoftTeams -Force
Connect-MicrosoftTeams
```

#### 1. ACS–Teams Federation

Enable Azure Communication Services federation so the bot can bridge audio into Teams meetings:

```powershell
# Get your ACS immutable resource ID
# az communication show --name <acs-resource-name> --resource-group <rg-name> \
#   --query "immutableResourceId" -o tsv

Set-CsTeamsAcsFederationConfiguration `
  -Identity Global `
  -EnableAcsUsers $true `
  -AllowedAcsResources @("<acs-immutable-resource-id>")

# Verify
Get-CsTeamsAcsFederationConfiguration
```

#### 2. Application Access Policy (for `#call` command)

The `#call` command creates Teams meetings on behalf of users via the Microsoft Graph API. Graph's `OnlineMeetings.ReadWrite.All` application permission requires a **Teams Application Access Policy** — this cannot be configured in any portal UI, only via PowerShell.

```powershell
# Create a policy allowing your bot's App ID to create meetings
New-CsApplicationAccessPolicy `
  -Identity "Labby-Voice-Policy" `
  -AppIds "<bot-app-client-id>" `
  -Description "Allow Labby Voice bot to create online meetings"

# Apply globally (all users can use #call)
Grant-CsApplicationAccessPolicy -PolicyName "Labby-Voice-Policy" -Global

# OR apply to specific users only:
# Grant-CsApplicationAccessPolicy -PolicyName "Labby-Voice-Policy" -Identity "user@domain.com"
```

> **Note:** Policy propagation can take **30–60 minutes**. The `#call` command will fail with a 403 error until propagation completes.

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

- `#call` — Start a voice session (creates a Teams meeting, bot joins, sends you the link)
- `#resources` — List all Azure resources
- `#resources vms` — List virtual machines
- `#resources <KQL>` — Run a custom Resource Graph query
- `#help` — Show available commands