from __future__ import annotations

import argparse
from dataclasses import dataclass

from .domains import resolve_enabled_domains


AUTH_CHOICES = ("interactive", "azcli", "env", "envvar")


@dataclass(frozen=True)
class ServerConfig:
    organization: str
    authentication: str
    tenant: str | None
    enabled_domains: set[str]

    @property
    def organization_url(self) -> str:
        return f"https://dev.azure.com/{self.organization}"


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    parser = argparse.ArgumentParser(
        prog="mcp-server-azuredevops-python",
        description="Azure DevOps MCP Server (Python)",
    )
    parser.add_argument("organization", help="Azure DevOps organization name")
    parser.add_argument(
        "-d",
        "--domains",
        action="append",
        default=[],
        help="Domain(s) to enable. Repeat the flag for multiple values, or pass 'all'.",
    )
    parser.add_argument(
        "-a",
        "--authentication",
        default="interactive",
        choices=AUTH_CHOICES,
        help="Authentication type",
    )
    parser.add_argument(
        "-t",
        "--tenant",
        default=None,
        help="Azure tenant ID (optional, used by interactive or azcli auth)",
    )

    ns = parser.parse_args(argv)
    enabled_domains = resolve_enabled_domains(ns.domains)

    return ServerConfig(
        organization=ns.organization,
        authentication=ns.authentication,
        tenant=ns.tenant,
        enabled_domains=enabled_domains,
    )
