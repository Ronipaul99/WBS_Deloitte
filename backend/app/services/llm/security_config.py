"""Lazy security readiness. No key generation and no startup/database/network activity."""

from dataclasses import dataclass, field

from app.services.llm.credentials import KeyRing
from app.services.llm.endpoint_policy import EndpointRegistry
from app.services.llm.errors import LlmSecurityError, SecurityCode


@dataclass(frozen=True)
class RuntimeSecurity:
    keys: KeyRing = field(repr=False)
    endpoints: EndpointRegistry = field(repr=False)


def load_runtime_security(settings) -> RuntimeSecurity:
    if not settings.llm_security_enabled:
        raise LlmSecurityError(SecurityCode.DISABLED)
    keys = KeyRing.load(
        source=settings.llm_credentials_keyring,
        secret_file=settings.llm_credentials_keyring_file,
        active_version=settings.llm_credentials_active_key,
    )
    endpoints = EndpointRegistry.parse(settings.llm_egress_policy)
    return RuntimeSecurity(keys, endpoints)


def security_readiness(settings) -> dict[str, object]:
    """For future feature readiness integration; existing health routes are unchanged."""
    if not settings.llm_security_enabled:
        return {"enabled": False, "ready": False, "code": SecurityCode.DISABLED.value}
    code = None
    try:
        load_runtime_security(settings)
    except LlmSecurityError as error:
        code = error.code.value
    return {"enabled": True, "ready": code is None, "code": code}
