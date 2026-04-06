from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from .ado_client import AzureDevOpsClients
from .auth import AuthError, TokenProvider
from .config import parse_args
from .tools_core import register_core_tools, register_mcp_apps_tools
from .tools_pipelines import register_pipeline_tools
from .tools_repositories import register_repository_tools
from .tools_work_items import register_work_item_tools


logger = logging.getLogger("ado_mcp_python")


def _configure_tools(mcp: FastMCP, clients: AzureDevOpsClients, enabled_domains: set[str]) -> None:
    if "mcp-apps" in enabled_domains:
        register_mcp_apps_tools(mcp)
    if "core" in enabled_domains:
        register_core_tools(mcp, clients)
    if "repositories" in enabled_domains:
        register_repository_tools(mcp, clients)
    if "work-items" in enabled_domains:
        register_work_item_tools(mcp, clients)
    if "pipelines" in enabled_domains:
        register_pipeline_tools(mcp, clients)


def main() -> None:
    config = parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info(
        "Starting Azure DevOps MCP Python server for organization=%s auth=%s domains=%s",
        config.organization,
        config.authentication,
        sorted(config.enabled_domains),
    )

    token_provider = TokenProvider(authentication=config.authentication, tenant=config.tenant)
    clients = AzureDevOpsClients(token_provider=token_provider, organization_url=config.organization_url)

    # Early auth check so failures happen before the MCP handshake.
    try:
        token_provider.get_token()
    except AuthError as exc:
        raise SystemExit(f"Authentication failed: {exc}") from exc

    mcp = FastMCP(name="Azure DevOps MCP Server (Python)")
    _configure_tools(mcp, clients, config.enabled_domains)
    mcp.run()


if __name__ == "__main__":
    main()
