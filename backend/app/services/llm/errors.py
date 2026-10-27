"""Public security failures contain codes only, never upstream diagnostics."""

from enum import StrEnum
from uuid import uuid4


class SecurityCode(StrEnum):
    DISABLED = "llm_security_disabled"
    KEY_CONFIGURATION = "llm_key_configuration"
    CREDENTIAL_INVALID = "llm_credential_invalid"
    CREDENTIAL_UNAVAILABLE = "llm_credential_unavailable"
    ACCESS_DENIED = "llm_access_denied"
    CONNECTION_DISABLED = "llm_connection_disabled"
    CREDENTIAL_CHANGED = "llm_credential_changed"
    ENDPOINT_DENIED = "llm_endpoint_denied"
    DNS_DENIED = "llm_dns_denied"
    DESTINATION_DENIED = "llm_destination_denied"
    TRANSPORT_UNSUPPORTED = "llm_transport_unsupported"
    TRANSPORT_FAILED = "llm_transport_failed"
    TIMEOUT = "llm_transport_timeout"
    RESPONSE_REJECTED = "llm_response_rejected"
    UPSTREAM_FAILED = "llm_upstream_failed"


class LlmSecurityError(Exception):
    def __init__(self, code: SecurityCode):
        self.code = SecurityCode(code)
        self.correlation_id = uuid4()
        super().__init__(self.code.value)

    def public(self) -> dict[str, str]:
        return {"code": self.code.value, "correlation_id": str(self.correlation_id)}
