from __future__ import annotations


_SSL_INJECTED = False


def enable_system_ssl_trust() -> None:
    """Inject OS trust store into Python SSL so requests/msrest can validate corp certs."""
    global _SSL_INJECTED
    if _SSL_INJECTED:
        return

    try:
        import truststore

        truststore.inject_into_ssl()
        _SSL_INJECTED = True
    except Exception:
        # Best-effort: keep behavior unchanged if truststore is unavailable.
        pass
