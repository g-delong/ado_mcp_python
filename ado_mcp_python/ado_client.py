from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication

from .auth import TokenProvider


@dataclass
class AzureDevOpsClients:
    token_provider: TokenProvider
    organization_url: str

    def _connection(self) -> Connection:
        token = self.token_provider.get_token()
        creds = BasicAuthentication("", token)
        return Connection(base_url=self.organization_url, creds=creds)

    def authorization_header(self) -> str:
        token = self.token_provider.get_token()
        auth_mode = (self.token_provider.authentication or "").lower()

        # PAT tokens are supplied through env/envvar mode and must use Basic auth.
        if auth_mode in {"env", "envvar"}:
            encoded = base64.b64encode(f":{token}".encode("utf-8")).decode("ascii")
            return f"Basic {encoded}"

        return f"Bearer {token}"

    def core(self) -> Any:
        return self._connection().clients.get_core_client()

    def git(self) -> Any:
        return self._connection().clients.get_git_client()

    def work_item_tracking(self) -> Any:
        return self._connection().clients.get_work_item_tracking_client()

    def work(self) -> Any:
        return self._connection().clients.get_work_client()

    def build(self) -> Any:
        return self._connection().clients.get_build_client()

    def pipelines(self) -> Any:
        return self._connection().clients.get_pipelines_client()
