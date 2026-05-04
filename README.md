# labby-voice

Voice-enabled Azure infrastructure assistant for Microsoft Teams.

## Architecture

```
Teams Call → ACS (audio bridge) → Voice Live API WebSocket → Python Agent
Teams Chat → M365 Agents SDK (aiohttp) → Python Agent
Python Agent → Azure Resource Graph → Azure Subscription Resources
```

- **app/**: Python agent using Microsoft 365 Agents SDK
- **terraform/**: Azure infrastructure (Bot Service, ACS, AI Foundry, Container App)
- **appPackage/**: Teams app manifest and icons

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

- `/resources` — List all Azure resources
- `/resources vms` — List virtual machines
- `/resources <KQL>` — Run a custom Resource Graph query
- `/help` — Show available commands