from __future__ import annotations

ALL_DOMAINS = {
    "advanced-security",
    "core",
    "mcp-apps",
    "pipelines",
    "repositories",
    "search",
    "test-plans",
    "wiki",
    "work",
    "work-items",
}


def resolve_enabled_domains(requested_domains: list[str] | None) -> set[str]:
    if not requested_domains:
        return set(ALL_DOMAINS)

    normalized = {d.strip().lower() for d in requested_domains if d and d.strip()}
    if "all" in normalized:
        return set(ALL_DOMAINS)

    unknown = normalized - ALL_DOMAINS
    if unknown:
        valid = ", ".join(sorted(ALL_DOMAINS))
        bad = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown domain(s): {bad}. Valid domains: {valid}, all")

    return normalized
