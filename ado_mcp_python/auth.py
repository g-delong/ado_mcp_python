from __future__ import annotations

import os
import subprocess
import time
import importlib
from dataclasses import dataclass


AZURE_DEVOPS_RESOURCE_APP_ID = "499b84ac-1321-427f-aa17-267ca6975798"
AZURE_DEVOPS_SCOPE = f"{AZURE_DEVOPS_RESOURCE_APP_ID}/.default"


class AuthError(RuntimeError):
    pass


@dataclass
class TokenProvider:
    authentication: str
    tenant: str | None = None
    _cached_token: str | None = None
    _cached_until: float = 0.0

    def get_token(self) -> str:
        now = time.time()
        if self._cached_token and now < self._cached_until:
            return self._cached_token

        token = self._fetch_token()
        # Conservative cache window to avoid using stale tokens.
        self._cached_token = token
        self._cached_until = now + 300
        return token

    def _fetch_token(self) -> str:
        auth = self.authentication.lower()

        if auth in {"env", "envvar"}:
            token = os.getenv("ADO_MCP_AUTH_TOKEN")
            if not token:
                raise AuthError("ADO_MCP_AUTH_TOKEN is not set for env/envvar authentication.")
            return token

        if auth == "azcli":
            cmd = [
                "az",
                "account",
                "get-access-token",
                "--resource",
                AZURE_DEVOPS_RESOURCE_APP_ID,
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ]
            if self.tenant:
                cmd.extend(["--tenant", self.tenant])

            try:
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            except FileNotFoundError as exc:
                raise AuthError("Azure CLI (az) is not installed or not on PATH.") from exc
            except subprocess.CalledProcessError as exc:
                message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
                raise AuthError(f"Failed to get token via Azure CLI: {message}") from exc

            token = result.stdout.strip()
            if not token:
                raise AuthError("Azure CLI returned an empty access token.")
            return token

        if auth == "interactive":
            try:
                azure_identity = importlib.import_module("azure.identity")
                DeviceCodeCredential = getattr(azure_identity, "DeviceCodeCredential")
            except ImportError as exc:
                raise AuthError("Interactive auth requires azure-identity. Install dependencies from pyproject.toml.") from exc

            credential = DeviceCodeCredential(tenant_id=self.tenant)
            token = credential.get_token(AZURE_DEVOPS_SCOPE).token
            if not token:
                raise AuthError("Interactive authentication did not return a token.")
            return token

        raise AuthError(f"Unsupported authentication mode: {self.authentication}")
