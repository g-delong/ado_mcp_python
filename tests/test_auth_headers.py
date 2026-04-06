from __future__ import annotations

import base64

from ado_mcp_python.ado_client import AzureDevOpsClients
from ado_mcp_python.auth import TokenProvider


def _clients_with_token(auth_mode: str, token: str) -> AzureDevOpsClients:
    provider = TokenProvider(authentication=auth_mode)
    provider._cached_token = token
    provider._cached_until = 9999999999
    return AzureDevOpsClients(token_provider=provider, organization_url="https://dev.azure.com/example")


def test_authorization_header_uses_basic_for_env_mode() -> None:
    clients = _clients_with_token("env", "pat-123")
    expected = base64.b64encode(b":pat-123").decode("ascii")
    assert clients.authorization_header() == f"Basic {expected}"


def test_authorization_header_uses_basic_for_envvar_mode() -> None:
    clients = _clients_with_token("envvar", "pat-456")
    expected = base64.b64encode(b":pat-456").decode("ascii")
    assert clients.authorization_header() == f"Basic {expected}"


def test_authorization_header_uses_bearer_for_azcli_mode() -> None:
    clients = _clients_with_token("azcli", "aad-token")
    assert clients.authorization_header() == "Bearer aad-token"


def test_authorization_header_uses_bearer_for_interactive_mode() -> None:
    clients = _clients_with_token("interactive", "aad-token-2")
    assert clients.authorization_header() == "Bearer aad-token-2"
