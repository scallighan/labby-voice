terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "=4.67.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "=3.1.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "=2.8.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.53.1"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    storage {
      data_plane_available = false
    }
  }

  storage_use_azuread = true

  subscription_id = var.subscription_id
}

resource "random_string" "unique" {
  length  = 8
  special = false
  upper   = false
}

data "azurerm_client_config" "current" {}

data "azurerm_log_analytics_workspace" "default" {
  name                = "DefaultWorkspace-${data.azurerm_client_config.current.subscription_id}-USW3" # hardcoding for now
  resource_group_name = "DefaultResourceGroup-USW3"
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.gh_repo}-${random_string.unique.result}-${local.loc_for_naming}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_storage_account" "this" {
  name                = "sa${local.func_name}${lower(local.loc_short)}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS"

  shared_access_key_enabled     = false
  public_network_access_enabled = false

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  network_rules {
    default_action = "Deny"
    bypass = [
      "AzureServices"
    ]
  }

  tags = local.tags

  lifecycle {
    ignore_changes = [ network_rules ]
  }
}

# give current user access to the storage account
resource "azurerm_role_assignment" "current_user_storage" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

# add a blob container to the storage account for the search service to use
resource "azurerm_storage_container" "search" {
  name                  = "search"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}


resource "azapi_resource" "ai_foundry" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  name                      = "aif${local.func_name}"
  parent_id                 = azurerm_resource_group.this.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = false

  body = {
    kind = "AIServices",
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }

    properties = {
      disableLocalAuth = true

      allowProjectManagement = true

      customSubDomainName = "aif${local.func_name}"

      publicNetworkAccess = "Enabled"
      networkAcls = {
        defaultAction = "Allow"
      }

    }
  }
}

resource "azapi_resource" "ai_foundry_project" {
  depends_on = [
    azapi_resource.ai_foundry
  ]

  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name                      = "fp${local.func_name}"
  parent_id                 = azapi_resource.ai_foundry.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = false

  body = {
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }

    properties = {
      displayName = "project"
      description = "A project for the AI Foundry account with network secured deployed Agent"
    }
  }

  response_export_values = [
    "identity.principalId",
    "properties.internalId"
  ]
}

# App Insight instance for monitoring
resource "azurerm_application_insights" "this" {
  name                = "appi${local.func_name}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  workspace_id = data.azurerm_log_analytics_workspace.default.id

  application_type = "other"
}

resource "azurerm_container_app_environment" "this" {
  name                       = "ace-${local.func_name}"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = data.azurerm_log_analytics_workspace.default.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  tags = local.tags
  lifecycle {
    ignore_changes = [
      infrastructure_resource_group_name,
      log_analytics_workspace_id
    ]
  }
}

resource "azurerm_container_app" "bot" {
  name                         = "aca-bot-${local.func_name}"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  secret {
    name  = "acs-connection-string"
    value = azurerm_communication_service.acs.primary_connection_string
  }

  template {
    container {
      name   = "bot"
      image  = "ghcr.io/${var.gh_repo}:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "RUNNING_ON_AZURE"
        value = "1"
      }

      env {
        name  = "TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }

      env {
        name  = "CLIENT_ID"
        value = azurerm_user_assigned_identity.bot.client_id
      }
      env {
        name  = "tenantId"
        value = data.azurerm_client_config.current.tenant_id
      }

      env {
        name  = "clientId"
        value = azurerm_user_assigned_identity.bot.client_id
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.bot.client_id
      }

      # new for M365 Agent SDK
      env {
        name  = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID"
        value = data.azurerm_client_config.current.tenant_id
      }
      env {
        name  = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID"
        value = azurerm_user_assigned_identity.bot.client_id
      }
      env {
        name  = "CONNECTIONS__SERVICE_CONNECTION__SETTINGS__AUTHTYPE"
        value = "UserManagedIdentity"
      }

      env {
        name  = "AZURE_AI_PROJECT_ENDPOINT"
        value = "https://aif${local.func_name}.services.ai.azure.com/api/projects/fp${local.func_name}"
      }

      env {
        name  = "FOUNDRY_MODEL"
        value = "gpt-5.4-mini"
      }

      env {
        name  = "AZURE_SPEECH_REGION"
        value = azurerm_resource_group.this.location
      }

      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }

      env {
        name        = "ACS_CONNECTION_STRING"
        secret_name = "acs-connection-string"
      }

      env {
        name  = "CALLBACK_BASE_URL"
        value = "https://aca-bot-${local.func_name}.${azurerm_container_app_environment.this.default_domain}"
      }

    }
    http_scale_rule {
      name                = "http-1"
      concurrent_requests = "100"
    }
    min_replicas = 1
    max_replicas = 1
  }

  ingress {
    allow_insecure_connections = false
    external_enabled           = true
    target_port                = 3978
    transport                  = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.bot.id]
  }
  tags = local.tags

  lifecycle {
    ignore_changes = [secret]
  }
}

resource "azurerm_user_assigned_identity" "bot" {
  location            = azurerm_resource_group.this.location
  name                = "uai-bot-${local.func_name}"
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_bot_service_azure_bot" "teamsbot" {
  name                    = "bot-${local.func_name}"
  resource_group_name     = azurerm_resource_group.this.name
  location                = "global"
  microsoft_app_id        = azurerm_user_assigned_identity.bot.client_id
  sku                     = "F0"
  endpoint                = "https://${azurerm_container_app.bot.ingress[0].fqdn}/api/messages"
  microsoft_app_msi_id    = azurerm_user_assigned_identity.bot.id
  microsoft_app_tenant_id = data.azurerm_client_config.current.tenant_id
  microsoft_app_type      = "UserAssignedMSI"
  tags                    = local.tags
}

resource "azurerm_bot_channel_ms_teams" "teams" {
  bot_name            = azurerm_bot_service_azure_bot.teamsbot.name
  location            = azurerm_bot_service_azure_bot.teamsbot.location
  resource_group_name = azurerm_resource_group.this.name
}

# give the bot identity access to foundry with Azure AI User role
resource "azurerm_role_assignment" "bot_foundry_access" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Azure AI User"
  principal_id         = azurerm_user_assigned_identity.bot.principal_id
}

resource "azurerm_role_assignment" "bot_search_access" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = azurerm_user_assigned_identity.bot.principal_id
}

# --- Voice Live API: Azure AI Speech ---

resource "azurerm_cognitive_account" "speech" {
  name                = "speech-${local.func_name}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  kind                = "SpeechServices"
  sku_name            = "S0"

  local_auth_enabled = false

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

resource "azurerm_role_assignment" "bot_speech_access" {
  scope                = azurerm_cognitive_account.speech.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.bot.principal_id
}

# --- Azure Communication Services ---

resource "azurerm_communication_service" "acs" {
  name                = "acs-${local.func_name}"
  resource_group_name = azurerm_resource_group.this.name
  data_location       = "United States"
  tags                = local.tags
}

# Event Grid subscription for ACS incoming call events → bot webhook
resource "azurerm_eventgrid_system_topic" "acs" {
  name                   = "evgt-acs-${local.func_name}"
  resource_group_name    = azurerm_resource_group.this.name
  location               = "global"
  source_resource_id = azurerm_communication_service.acs.id
  topic_type             = "Microsoft.Communication.CommunicationServices"
  tags                   = local.tags
}

resource "azurerm_eventgrid_system_topic_event_subscription" "acs_incoming_call" {
  name                = "incoming-call-${local.func_name}"
  system_topic        = azurerm_eventgrid_system_topic.acs.name
  resource_group_name = azurerm_resource_group.this.name

  webhook_endpoint {
    url = "https://${azurerm_container_app.bot.ingress[0].fqdn}/api/calls/events"
  }

  included_event_types = [
    "Microsoft.Communication.IncomingCall",
  ]
}

# --- Resource Graph: Reader role on subscription ---

resource "azurerm_role_assignment" "bot_subscription_reader" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.bot.principal_id
}