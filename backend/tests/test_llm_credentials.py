"""Step 3 encryption/configuration/lifecycle checks; run with --noconftest."""

import base64
import json
import os
from dataclasses import replace

import pytest
from agent_schema_fixtures import access, uid
from llm_security_fixtures import SENTINEL, endpoint, keys
from llm_security_fixtures import sessions as sessions
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.models.auth import AuthEvent
from app.models.domain import TenantMembership, User
from app.models.llm import LlmConnection, LlmCredentialVersion, LlmModelProfileVersion
from app.services.llm.credential_service import CredentialService
from app.services.llm.credentials import (
    CredentialAudit,
    CredentialBinding,
    CredentialChange,
    CredentialStatus,
    KeyRing,
    decrypt_credential,
    encrypt_credential,
    parse_credential_change,
)
from app.services.llm.endpoint_policy import EndpointRegistry, OperatorPolicy, PinnedEndpoint
from app.services.llm.errors import LlmSecurityError, SecurityCode
from app.services.llm.security_config import load_runtime_security, security_readiness


def binding():
    return CredentialBinding(uid(1), uid(5), uid(50), 1)


def test_authenticated_encryption_roundtrip_and_fresh_nonces():
    ring = keys()
    outputs = [encrypt_credential(ring, binding(), SecretStr(SENTINEL)) for _ in range(100)]
    assert len({value.nonce for value in outputs}) == 100
    assert all(SENTINEL.encode() not in value.ciphertext for value in outputs)
    assert decrypt_credential(ring, binding(), outputs[0]).get_secret_value() == SENTINEL
    assert SENTINEL not in repr(outputs[0]) + repr(ring)


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": uid(101)},
        {"connection_id": uid(105)},
        {"credential_id": uid(150)},
        {"credential_version": 2},
    ],
)
def test_aad_scope_and_version_substitution_fails(change):
    ring = keys()
    envelope = encrypt_credential(ring, binding(), SecretStr(SENTINEL))
    with pytest.raises(LlmSecurityError) as error:
        decrypt_credential(ring, replace(binding(), **change), envelope)
    assert error.value.code == SecurityCode.CREDENTIAL_INVALID
    assert error.value.__context__ is None


@pytest.mark.parametrize("change", ["ciphertext", "nonce", "key_version", "truncated"])
def test_envelope_tampering_fails_safely(change):
    ring = keys()
    envelope = encrypt_credential(ring, binding(), SecretStr(SENTINEL))
    if change == "ciphertext":
        envelope = replace(
            envelope, ciphertext=bytes([envelope.ciphertext[0] ^ 1]) + envelope.ciphertext[1:]
        )
    elif change == "nonce":
        envelope = replace(envelope, nonce=b"z" * 12)
    elif change == "key_version":
        envelope = replace(envelope, key_version="v2")
    else:
        envelope = replace(envelope, ciphertext=b"")
    with pytest.raises(LlmSecurityError) as error:
        decrypt_credential(ring, binding(), envelope)
    assert SENTINEL not in str(error.value) + repr(error.value.public())


def test_rotation_backup_restore_and_lost_key():
    original = base64.urlsafe_b64encode(os.urandom(32)).decode()
    newer = base64.urlsafe_b64encode(os.urandom(32)).decode()
    old = KeyRing.parse(SecretStr(json.dumps({"old": original})), "old")
    combined = KeyRing.parse(SecretStr(json.dumps({"old": original, "new": newer})), "new")
    envelope = encrypt_credential(old, binding(), SecretStr(SENTINEL))
    secret = decrypt_credential(combined, binding(), envelope)
    rewrapped = encrypt_credential(combined, replace(binding(), credential_version=2), secret)
    assert rewrapped.key_version == "new" and rewrapped.nonce != envelope.nonce
    new_only = KeyRing.parse(SecretStr(json.dumps({"new": newer})), "new")
    with pytest.raises(LlmSecurityError):
        decrypt_credential(new_only, binding(), envelope)
    assert decrypt_credential(old, binding(), envelope).get_secret_value() == SENTINEL


@pytest.mark.parametrize(
    "raw,active",
    [
        (None, None),
        ("{}", "v1"),
        ("not-json", "v1"),
        ('{"v1":"short"}', "v1"),
        ('{"v1":"a","v1":"b"}', "v1"),
        ('{"v1":"' + "x" * 33000 + '"}', "v1"),
    ],
    ids=["absent", "empty", "not-json", "short", "duplicate", "oversized"],
)
def test_keyring_missing_malformed_duplicate_or_oversized(raw, active):
    with pytest.raises(LlmSecurityError) as error:
        KeyRing.parse(SecretStr(raw) if raw is not None else None, active)
    assert error.value.code == SecurityCode.KEY_CONFIGURATION
    assert error.value.__context__ is None


def test_operator_key_file_is_bounded_and_exclusive(tmp_path):
    path = tmp_path / "ephemeral-test-keyring.json"
    path.write_text(json.dumps({"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()}))
    path.chmod(0o600)
    ring = KeyRing.load(source=None, secret_file=path, active_version="v1")
    assert ring.active_version == "v1"
    with pytest.raises(LlmSecurityError):
        KeyRing.load(source=SecretStr("{}"), secret_file=path, active_version="v1")
    with pytest.raises(LlmSecurityError):
        KeyRing.load(source=None, secret_file=tmp_path, active_version="v1")
    path.write_bytes(b"x" * 32769)
    with pytest.raises(LlmSecurityError):
        KeyRing.load(source=None, secret_file=path, active_version="v1")


@pytest.mark.parametrize(
    "payload",
    [
        {"secret": None},
        {"secret": SENTINEL},
        {"action": "replace"},
        {"action": "replace", "secret": ""},
        {"action": "replace", "secret": "\r\nvalue"},
        {"action": "rotate", "secret": SENTINEL},
        {"action": "clear", "secret": ""},
        {"action": "disable", "secret": SENTINEL},
    ],
)
def test_explicit_secret_update_semantics_reject_ambiguous_input(payload):
    with pytest.raises((ValidationError, LlmSecurityError)):
        CredentialChange.model_validate(payload)


def test_request_and_response_serialization_never_returns_plaintext():
    change = CredentialChange(action="replace", secret=SecretStr(SENTINEL))
    assert "secret" not in change.model_dump()
    assert SENTINEL not in change.model_dump_json() + repr(change)
    assert CredentialChange().action == "preserve"
    assert CredentialChange(action="rotate").secret is None
    assert "secret" not in CredentialStatus.model_fields
    assert "secret" not in CredentialAudit.model_fields
    assert CredentialChange.model_json_schema()["properties"]["secret"]["anyOf"][0]["writeOnly"]


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "unsupported", "secret": SENTINEL},
        {"secret": SENTINEL},
        {"action": "replace", "secret": SENTINEL, "unknown": SENTINEL},
        {"action": "replace", "secret": {"unexpected": SENTINEL}},
    ],
)
def test_write_boundary_discards_raw_pydantic_error_inputs(payload):
    with pytest.raises(LlmSecurityError) as error:
        parse_credential_change(payload)
    assert error.value.__context__ is None
    assert SENTINEL not in str(error.value) + repr(error.value.public())
    assert parse_credential_change({}).action == "preserve"


def test_key_version_is_authenticated_even_when_key_bytes_are_aliased():
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    ring = KeyRing.parse(SecretStr(json.dumps({"old": key, "alias": key})), "old")
    envelope = encrypt_credential(ring, binding(), SecretStr(SENTINEL))
    with pytest.raises(LlmSecurityError):
        decrypt_credential(ring, binding(), replace(envelope, key_version="alias"))


def test_valid_readiness_and_missing_egress_policy_are_explicit():
    registry, _ = endpoint()
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings = Settings(
        _env_file=None,
        auth_mode="development",
        document_ingestion_enabled=False,
        document_ingestion_local_development=False,
        llm_security_enabled=True,
        llm_credentials_keyring=SecretStr(json.dumps({"v1": key})),
        llm_credentials_active_key="v1",
        llm_egress_policy=SecretStr(registry._policy.model_dump_json()),
    )
    assert security_readiness(settings) == {"enabled": True, "ready": True, "code": None}
    assert key not in repr(load_runtime_security(settings)) + settings.model_dump_json()
    settings.llm_egress_policy = None
    assert security_readiness(settings)["code"] == SecurityCode.ENDPOINT_DENIED


def test_settings_lazy_readiness_and_serialization_exclude_keyring():
    settings = Settings(
        _env_file=None,
        auth_mode="development",
        document_ingestion_enabled=False,
        document_ingestion_local_development=False,
        llm_credentials_keyring=SecretStr(SENTINEL),
    )
    assert not settings.llm_security_enabled
    assert security_readiness(settings)["code"] == SecurityCode.DISABLED.value
    assert SENTINEL not in settings.model_dump_json() + repr(settings)
    settings.llm_security_enabled = True
    assert security_readiness(settings)["code"] == SecurityCode.KEY_CONFIGURATION.value
    with pytest.raises(LlmSecurityError):
        load_runtime_security(settings)


@pytest.mark.asyncio
async def test_scoped_lifecycle_storage_and_metadata_only_audit(sessions):
    registry, pinned = endpoint()
    ring = keys()
    service = CredentialService(sessions, access(), ring, registry)
    first = await service.update(
        uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL))
    )
    preserved = await service.update(uid(5), CredentialChange())
    assert first == preserved and first.configured
    resolved = await service.prepare(uid(5), pinned, "test")
    assert resolved.secret.get_secret_value() == SENTINEL
    assert SENTINEL not in repr(resolved)
    await service.verify(resolved.receipt, pinned)
    second = await service.update(uid(5), CredentialChange(action="rotate"))
    assert second.credential_version == 2 and second.credential_id != first.credential_id
    with pytest.raises(LlmSecurityError) as changed:
        await service.verify(resolved.receipt, pinned)
    assert changed.value.code == SecurityCode.CREDENTIAL_CHANGED
    fresh = await service.prepare(uid(5), pinned, "test")
    assert fresh.receipt.credential_version == 2
    await service.update(uid(5), CredentialChange(action="disable"))
    with pytest.raises(LlmSecurityError) as disabled:
        await service.prepare(uid(5), pinned, "test")
    assert disabled.value.code == SecurityCode.CONNECTION_DISABLED
    cleared = await service.update(uid(5), CredentialChange(action="clear"))
    assert not cleared.configured and not cleared.enabled
    async with sessions() as session:
        records = (await session.scalars(select(LlmCredentialVersion))).all()
        assert len(records) == 2 and all(item.retired_at is not None for item in records)
        assert all(SENTINEL.encode() not in item.ciphertext for item in records)
        audit = (await session.scalars(select(AuthEvent))).all()
        assert {item.event_type for item in audit} >= {
            "llm_replace",
            "llm_rotate",
            "llm_disable",
            "llm_clear",
        }
        assert SENTINEL not in json.dumps([item.details for item in audit])


@pytest.mark.asyncio
@pytest.mark.parametrize("user,tenant", [(19, 1), (29, 1), (109, 101)])
async def test_admin_only_updates_and_cross_tenant_denial(sessions, user, tenant):
    registry, _ = endpoint()
    service = CredentialService(sessions, access(user, tenant), keys(), registry)
    with pytest.raises(LlmSecurityError) as error:
        await service.update(uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL)))
    assert error.value.code == SecurityCode.ACCESS_DENIED


@pytest.mark.asyncio
async def test_clear_and_disable_work_without_encryption_keys(sessions):
    registry, _ = endpoint()
    service = CredentialService(sessions, access(), None, registry)
    assert (await service.update(uid(5), CredentialChange())).configured is False
    assert not (await service.update(uid(5), CredentialChange(action="disable"))).enabled
    assert not (await service.update(uid(5), CredentialChange(action="clear"))).configured
    with pytest.raises(LlmSecurityError):
        await service.update(uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL)))


@pytest.mark.asyncio
async def test_pinned_endpoint_changes_block_current_calls(sessions):
    registry, pinned = endpoint()
    service = CredentialService(sessions, access(), keys(), registry)
    await service.update(uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL)))
    async with sessions.begin() as session:
        row = await session.get(LlmConnection, uid(5))
        row.endpoint_policy = {"host": "unapproved.example.invalid", "path_prefix": "/v1"}
    with pytest.raises(LlmSecurityError) as error:
        await service.prepare(uid(5), pinned, "inference")
    assert error.value.code == SecurityCode.ENDPOINT_DENIED


@pytest.mark.asyncio
async def test_current_membership_and_user_status_are_rechecked_per_attempt(sessions):
    registry, pinned = endpoint()
    manager = CredentialService(sessions, access(), keys(), registry)
    await manager.update(uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL)))
    editor = CredentialService(sessions, access(19), manager._keys, registry)
    receipt = (await editor.prepare(uid(5), pinned, "test")).receipt
    with pytest.raises(LlmSecurityError):
        await editor.status(uid(5))
    for user, tenant in ((29, 1), (109, 101)):
        denied = CredentialService(sessions, access(user, tenant), manager._keys, registry)
        with pytest.raises(LlmSecurityError):
            await denied.prepare(uid(5), pinned, "test")
    async with sessions.begin() as session:
        member = await session.scalar(
            select(TenantMembership).where(TenantMembership.user_id == uid(19))
        )
        member.role = "VIEWER"
    with pytest.raises(LlmSecurityError) as denied:
        await editor.verify(receipt, pinned)
    assert denied.value.code == SecurityCode.ACCESS_DENIED
    async with sessions.begin() as session:
        user = await session.get(User, uid(9))
        user.is_active = False
    with pytest.raises(LlmSecurityError):
        await manager.prepare(uid(5), pinned, "test")


@pytest.mark.asyncio
async def test_rotation_preserves_pinned_configuration_and_uses_active_key(sessions):
    registry, _ = endpoint()
    old_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    new_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    old_ring = KeyRing.parse(SecretStr(json.dumps({"old": old_key})), "old")
    service = CredentialService(sessions, access(), old_ring, registry)
    await service.update(uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL)))
    async with sessions() as session:
        before = (await session.get(LlmModelProfileVersion, uid(21))).snapshot
        policy = (await session.get(LlmConnection, uid(5))).endpoint_policy
    new_ring = KeyRing.parse(SecretStr(json.dumps({"old": old_key, "new": new_key})), "new")
    service = CredentialService(sessions, access(), new_ring, registry)
    current = await service.update(uid(5), CredentialChange(action="rotate"))
    assert current.key_version == "new" and current.credential_version == 2
    async with sessions() as session:
        assert (await session.get(LlmModelProfileVersion, uid(21))).snapshot == before
        assert (await session.get(LlmConnection, uid(5))).endpoint_policy == policy


@pytest.mark.asyncio
async def test_revocation_does_not_need_a_lost_key_and_failed_rotation_is_atomic(sessions):
    registry, pinned = endpoint()
    service = CredentialService(sessions, access(), keys(), registry)
    previous = await service.update(
        uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL))
    )
    lost = CredentialService(sessions, access(), None, registry)
    with pytest.raises(LlmSecurityError):
        await lost.update(uid(5), CredentialChange(action="rotate"))
    assert await lost.status(uid(5)) == previous
    await lost.update(uid(5), CredentialChange(action="disable"))
    with pytest.raises(LlmSecurityError):
        await service.prepare(uid(5), pinned, "test")
    assert not (await lost.update(uid(5), CredentialChange(action="clear"))).configured


@pytest.mark.asyncio
async def test_service_revalidates_operator_purpose_even_without_transport(sessions):
    _, original = endpoint()
    approval = original.approval.model_copy(update={"purposes": ("test",)})
    pinned = PinnedEndpoint(approval)
    registry = EndpointRegistry(OperatorPolicy(endpoints=(approval,)))
    service = CredentialService(sessions, access(), keys(), registry)
    await service.update(uid(5), CredentialChange(action="replace", secret=SecretStr(SENTINEL)))
    receipt = (await service.prepare(uid(5), pinned, "test")).receipt
    with pytest.raises(LlmSecurityError) as error:
        await service.prepare(uid(5), pinned, "inference")
    assert error.value.code == SecurityCode.ENDPOINT_DENIED
    with pytest.raises(LlmSecurityError):
        await service.verify(receipt.model_copy(update={"purpose": "inference"}), pinned)
