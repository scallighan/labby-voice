"""Azure Resource Graph query tool for the agent."""

import logging

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest

logger = logging.getLogger(__name__)


def _get_credential(running_on_azure: bool, client_id: str | None = None):
    if running_on_azure and client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential()


async def query_resources(
    query: str,
    subscription_id: str,
    running_on_azure: bool = False,
    client_id: str | None = None,
) -> list[dict]:
    """Run an Azure Resource Graph query and return results as a list of dicts.

    Args:
        query: Kusto (KQL) query string for Azure Resource Graph.
        subscription_id: Azure subscription ID to scope the query.
        running_on_azure: Whether running on Azure (uses Managed Identity).
        client_id: Client ID for User Assigned Managed Identity.
    """
    credential = _get_credential(running_on_azure, client_id)
    client = ResourceGraphClient(credential)

    request = QueryRequest(
        subscriptions=[subscription_id],
        query=query,
    )

    try:
        response = client.resources(request)
        return response.data
    except Exception:
        logger.exception("Resource Graph query failed")
        raise


# Common queries for convenience
QUERIES = {
    "all_resources": ("Resources | project name, type, location, resourceGroup | order by type asc"),
    "vms": (
        "Resources | where type == 'microsoft.compute/virtualmachines'"
        " | project name, location, resourceGroup, properties.hardwareProfile.vmSize"
    ),
    "app_services": ("Resources | where type == 'microsoft.web/sites' | project name, location, resourceGroup, kind"),
    "storage_accounts": (
        "Resources | where type == 'microsoft.storage/storageaccounts'"
        " | project name, location, resourceGroup, sku.name"
    ),
    "aks_clusters": (
        "Resources | where type == 'microsoft.containerservice/managedclusters' | project name, location, resourceGroup"
    ),
    "resource_count_by_type": ("Resources | summarize count() by type | order by count_ desc"),
}
