"""AES-256-GCM envelope and write-only credential contracts. No configured secrets."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import Field, SecretStr, ValidationError, model_validator

from app.services.llm.contracts import Contract, Identity, Positive, Version
from app.services.llm.errors import LlmSecurityError, SecurityCode

MAX_SECRET_BYTES = 8192


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def validated_secret(secret: SecretStr) -> bytes:
    raw = secret.get_secret_value() if isinstance(secret, SecretStr) else None
    # Header-safe opaque API credentials. Newlines/control/non-ASCII are not supported.
    if (
        raw is None
        or not 1 <= len(raw) <= MAX_SECRET_BYTES
        or any(ord(char) < 33 or ord(char) > 126 for char in raw)
    ):
        raise LlmSecurityError(SecurityCode.CREDENTIAL_INVALID)
    return raw.encode("ascii")


@dataclass(frozen=True, slots=True)
class KeyRing:
    active_version: str
    _keys: object = field(repr=False)

    @classmethod
    def parse(cls, source: SecretStr | None, active_version: str | None) -> KeyRing:
        keys = None
        try:
            raw = source.get_secret_value() if source is not None else ""
            if len(raw.encode("utf-8")) > 32768:
                raise ValueError("key ring too large")
            data = json.loads(raw, object_pairs_hook=_pairs)
            if not isinstance(data, dict) or not 1 <= len(data) <= 16:
                raise ValueError("invalid key ring")
            decoded = {}
            for name, value in data.items():
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", name) or not isinstance(
                    value, str
                ):
                    raise ValueError("invalid key ring")
                key = base64.b64decode(value, altchars=b"-_", validate=True)
                if len(key) != 32 or base64.urlsafe_b64encode(key).decode("ascii") != value:
                    raise ValueError("invalid key size/encoding")
                decoded[name] = key
            if active_version not in decoded:
                raise ValueError("active encryption key unavailable")
            keys = MappingProxyType(decoded)
        except (ValueError, TypeError, AttributeError, UnicodeError):
            pass
        if keys is None:
            # Raise outside the except block: no raw JSON/key validation exception context.
            raise LlmSecurityError(SecurityCode.KEY_CONFIGURATION)
        return cls(active_version, keys)

    @classmethod
    def load(
        cls, *, source: SecretStr | None, secret_file: Path | None, active_version: str | None
    ) -> KeyRing:
        if source is not None and secret_file is not None:
            raise LlmSecurityError(SecurityCode.KEY_CONFIGURATION)
        if secret_file is None:
            return cls.parse(source, active_version)
        raw = None
        try:
            # Secret files are operator-supplied, never request paths. Do not follow symlinks.
            info = secret_file.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_size > 32768
                or (os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077)
            ):
                raise ValueError("unsafe secret file")
            flags = (
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            with os.fdopen(os.open(secret_file, flags), "rb") as handle:
                opened = os.fstat(handle.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError("secret file changed")
                if not stat.S_ISREG(opened.st_mode) or (
                    os.name == "posix" and stat.S_IMODE(opened.st_mode) & 0o077
                ):
                    raise ValueError("unsafe secret file")
                raw = handle.read(32769)
            if len(raw) > 32768:
                raw = None
        except (OSError, ValueError):
            pass
        if raw is None:
            raise LlmSecurityError(SecurityCode.KEY_CONFIGURATION)
        decoded = None
        try:
            decoded = raw.decode("utf-8")
        except UnicodeError:
            pass
        if decoded is None:
            raise LlmSecurityError(SecurityCode.KEY_CONFIGURATION)
        return cls.parse(SecretStr(decoded), active_version)

    def key(self, version: str) -> bytes:
        key = self._keys.get(version)
        if key is None:
            raise LlmSecurityError(SecurityCode.KEY_CONFIGURATION)
        return key


@dataclass(frozen=True, slots=True)
class CredentialBinding:
    tenant_id: UUID
    connection_id: UUID
    credential_id: UUID
    credential_version: int

    def __post_init__(self):
        if (
            any(
                not isinstance(value, UUID) or value.int == 0
                for value in (self.tenant_id, self.connection_id, self.credential_id)
            )
            or type(self.credential_version) is not int
            or self.credential_version < 1
        ):
            raise LlmSecurityError(SecurityCode.CREDENTIAL_INVALID)

    def aad(self, key_version: str) -> bytes:
        # Fixed JSON array avoids ambiguous concatenation and binds envelope format/algorithm.
        return json.dumps(
            [
                "wbs-llm-credential-v1",
                "AES-256-GCM",
                str(self.tenant_id),
                str(self.connection_id),
                str(self.credential_id),
                self.credential_version,
                key_version,
            ],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class EncryptedCredential:
    ciphertext: bytes = field(repr=False)
    nonce: bytes = field(repr=False)
    key_version: str


def encrypt_credential(ring: KeyRing, binding: CredentialBinding, secret: SecretStr):
    plaintext = validated_secret(secret)
    nonce = os.urandom(12)
    version = ring.active_version
    ciphertext = AESGCM(ring.key(version)).encrypt(nonce, plaintext, binding.aad(version))
    return EncryptedCredential(ciphertext, nonce, version)


def decrypt_credential(ring: KeyRing, binding: CredentialBinding, envelope: EncryptedCredential):
    if (
        not isinstance(envelope.nonce, bytes)
        or len(envelope.nonce) != 12
        or not isinstance(envelope.ciphertext, bytes)
        or not 17 <= len(envelope.ciphertext) <= MAX_SECRET_BYTES + 16
    ):
        raise LlmSecurityError(SecurityCode.CREDENTIAL_INVALID)
    plaintext = None
    key = ring.key(envelope.key_version)
    try:
        plaintext = (
            AESGCM(key)
            .decrypt(envelope.nonce, envelope.ciphertext, binding.aad(envelope.key_version))
            .decode("ascii")
        )
    except (InvalidTag, ValueError, UnicodeError):
        pass
    if plaintext is None:
        raise LlmSecurityError(SecurityCode.CREDENTIAL_INVALID)
    secret = SecretStr(plaintext)
    validated_secret(secret)
    return secret


class CredentialChange(Contract):
    """Omitted secret preserves. Null/empty is never interpreted as clear."""

    action: Literal["preserve", "replace", "clear", "rotate", "disable"] = "preserve"
    secret: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def explicit_semantics(self):
        supplied = "secret" in self.model_fields_set
        if self.action == "replace":
            if self.secret is None:
                raise ValueError("replacement credential required")
            validated_secret(self.secret)
        elif supplied:
            raise ValueError("this action does not accept a secret")
        return self


def parse_credential_change(payload: object) -> CredentialChange:
    """Write boundary: never export Pydantic's raw input/error dictionaries."""
    parsed = None
    try:
        parsed = CredentialChange.model_validate(payload)
    except (ValidationError, LlmSecurityError):
        pass
    if parsed is None:
        raise LlmSecurityError(SecurityCode.CREDENTIAL_INVALID)
    return parsed


class CredentialStatus(Contract):
    connection_id: Identity
    configured: Annotated[bool, Field(strict=True)]
    enabled: Annotated[bool, Field(strict=True)]
    credential_id: Identity | None = None
    credential_version: Positive | None = None
    key_version: Version | None = None


class CredentialAudit(Contract):
    tenant_id: Identity
    actor_id: Identity
    connection_id: Identity
    action: Literal["preserve", "replace", "clear", "rotate", "disable", "call_authorized"]
    credential_id: Identity | None = None
    credential_version: Positive | None = None
    key_version: Version | None = None


class CredentialReceipt(Contract):
    attempt_id: Identity
    tenant_id: Identity
    actor_id: Identity
    connection_id: Identity
    credential_id: Identity
    credential_version: Positive
    key_version: Version
    endpoint_approval_id: Identity
    purpose: Literal["discovery", "test", "inference"]


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    receipt: CredentialReceipt
    secret: SecretStr = field(repr=False)
