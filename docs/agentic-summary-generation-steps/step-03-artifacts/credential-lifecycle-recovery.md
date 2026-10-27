# Credentials, runtime keys and recovery

## Envelope and associated data

The credential envelope uses the existing `cryptography` dependency and AES-256-GCM.
Each encryption uses a fresh random 12-byte nonce and a 32-byte encryption key.
Ciphertext includes the authentication tag. Runtime keys never enter the database.
The fixed UTF-8/ASCII compact JSON AAD array is:

```text
["wbs-llm-credential-v1","AES-256-GCM","<TENANT_UUID>","<CONNECTION_UUID>","<CREDENTIAL_UUID>",<POSITIVE_CREDENTIAL_VERSION>,"<ENCRYPTION_KEY_VERSION>"]
```

UUIDs use canonical Python UUID strings; JSON has no whitespace. The key version
is authenticated even when two key-ring labels happen to contain identical key
bytes. Wrong scope, altered nonce/tag/ciphertext or malformed envelopes fail with
controlled codes. An unavailable decryption key produces `llm_key_configuration`.
There is no plaintext/legacy fallback. DB ciphertext/nonce/key-version columns fit
the Step 2 bounds without changing any migration.

Opaque API credentials are limited to 1-8192 printable ASCII characters without
whitespace or control bytes. Empty/null input does not mean clear. Unsupported
credential types must remain unavailable until explicitly designed and tested.

## Write-only lifecycle

Use `parse_credential_change` at a future request boundary. It converts invalid
input into a safe `LlmSecurityError`; never return Pydantic `.errors()` dictionaries,
which can contain raw submitted inputs. `CredentialChange` is frozen, rejects extra
fields and excludes the secret from serialization/repr. The secret field is marked
write-only in JSON Schema. No request route exists in this step.

| Action | Input | Effect |
| --- | --- | --- |
| preserve | Omit action and secret, or explicit `preserve` without secret | Retain current credential and enabled state; no key required |
| replace | Explicit `replace` plus nonempty secret | New provider API credential in a fresh encrypted version/UUID; retire previous active version; retain enabled state |
| rotate | Explicit `rotate`, no secret | Re-encrypt the existing provider API credential with the active encryption key, new version/UUID/nonce; retire previous version; retain enabled state |
| clear | Explicit `clear`, no secret | Retire active version, remove pointer and disable connection; no decryption required |
| disable | Explicit `disable`, no secret | Disable new calls but retain encrypted credential/pointer; no decryption required |

Supplying a secret with any action except replace is rejected, including null or
empty values. Replace and rotate do not enable a disabled connection. Rotation
here means encryption-key rewrapping; **provider-token rotation uses replace** and
separate revocation of the old token at its issuer. Nothing calls the issuer here.
There is no enable operation in this step.

Lifecycle operations require current active tenant/user membership and `llm:manage`.
Metadata responses include only configured/enabled state and identifiers/versions.
Attempts require `llm:use` with the existing summary-update permission rule.
Connection IDs and authenticated `StorageAccess` come from trusted backend context.
They must never be chosen by a model/tool or treated as authorization by themselves.

Each attempt resolves the current non-retired credential of the same connection,
records a secret-free attempt receipt, then rechecks current permissions, enabled
state, endpoint approval and active credential immediately before every wire write.
Rotation invalidates an old receipt; a later explicit attempt must resolve again.
Disable/clear block new attempts. There is no automatic retry or provider fallback.
Pinned endpoint, model profile and workflow inputs are never rewritten by lifecycle
operations. Revocation cannot recall bytes already sent; a concurrent change after
the final check can race an in-flight write. Production transaction/race testing is
pending. Later orchestration must fence/cancel in-flight work as separately designed.

## Runtime configuration (placeholders only)

These settings are documented here without editing any local `.env` or deployment:

```dotenv
LLM_SECURITY_ENABLED=false
LLM_CREDENTIALS_ACTIVE_KEY=<ENCRYPTION_KEY_VERSION>
LLM_CREDENTIALS_KEYRING_FILE=/run/secrets/<LLM_KEYRING_FILE>
# Alternative to KEYRING_FILE, never supply both:
# LLM_CREDENTIALS_KEYRING={"<ENCRYPTION_KEY_VERSION>":"<BASE64URL_32_BYTE_KEY>"}
LLM_EGRESS_POLICY={"endpoints":[{"approval_id":"<APPROVAL_UUID>","host":"<APPROVED_PUBLIC_HTTPS_HOST>","port":443,"path_prefix":"/<APPROVED_PREFIX>","auth_scheme":"bearer","purposes":["discovery","test","inference"]}]}
```

The file contains the same JSON key-ring object as the inline alternative. Keys
are canonical padded URL-safe base64 for exactly 32 random bytes; labels contain
1-80 ASCII letters/digits/dots/underscores/hyphens and start with a letter/digit.
Ring size is 1-16 keys, at most 32768 bytes. Active version must exist. Reject
duplicate JSON keys and ambiguous input sources. Policy size is at most 65536
bytes/64 approvals. The examples above are deliberately incomplete placeholders.

Provision through an operator secret manager or separately mounted secret file,
outside repository, DB, frontend build and ordinary logs. File loading rejects
symlinks/nonregular files, enforces a bounded read and checks that the opened file
matches the inspected identity. POSIX group/other access is rejected; provision
owner-only access. On Windows, restrictive ACL enforcement is an operator obligation;
POSIX permission-bit checks do not establish Windows ACL isolation. Do not place
secrets in process arguments, shell history, chat, fixtures or tracked examples.

`load_runtime_security` and `security_readiness` are explicit future integration
primitives. Missing/malformed secrets or policy fail closed when requested. Startup
and existing health routes are unchanged; disabled LLM security does not inspect
key files. The flag is default false and does not implement or enable generation.

## Backup, rotation and lost-key handling

1. Before storing real credentials, provision independent runtime encryption keys
   and test restoration using ephemeral synthetic credentials in a disposable DB.
   Back up the ring/labels separately from DB backups, with restricted access and
   an audited recovery owner. A DB snapshot alone is insufficient for decryption.
2. Add a new independent 32-byte key/version to the separately managed ring; keep
   old versions. Distribute the combined ring to all future credential-using
   processes before choosing the new active version. This task provisions nothing.
3. Use `rotate` per connection to create new encrypted credential versions. Preserve
   old keys for retained historical ciphertext and recoverable DB backups. There
   is no bulk rotation service or automatic historical re-encryption here.
4. Verify synthetic restore/decryption and fresh-attempt behavior before retiring
   any old key. Keep required keys through backup retention or deliberately accept
   that old snapshots cannot decrypt credentials. Do not delete retained rows to
   bypass Step 2 immutability/lifecycle policy.
5. If a key is lost, affected credentials fail closed. Disable/clear remains
   available without that key. Restore the exact version/key from its independent
   backup, or obtain a newly issued provider token and use replace with a healthy
   active key. Neither ciphertext nor the DB can reconstruct a lost key. Never
   disable authentication, use plaintext storage or select a different provider.
6. If compromise is suspected, disable the connection and revoke/rotate the token
   at its issuer through an authorized operator channel. Rotating the encryption
   key alone cannot invalidate stolen API tokens or already exposed DB snapshots.

This is an operational procedure, not evidence that a deployed key backup or
recovery has been tested. Only synthetic local recovery tests have run.
