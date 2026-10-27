# Provider Configuration Record

Complete this record for each environment. Store secret values in the approved secret manager; this
document contains references and non-secret metadata only.

## Registration

| Decision | Approved value |
|---|---|
| Provider and directory owner | Pending |
| OIDC issuer | Pending |
| Discovery URL | Pending |
| Client ID / audience | Pending |
| Client type | Confidential web client |
| Redirect URI | `https://<api-host>/api/v1/auth/sso/callback` |
| UI completion URI | `https://<ui-host>/sso/callback` (not provider-registered) |
| Authorization endpoint pin | Pending |
| Token endpoint pin | Pending |
| JWKS endpoint pin | Pending |
| Approved algorithms | `RS256` unless security review approves another configured value |
| Provider directory ID | Pending |
| Immutable subject claim | `sub` |
| Directory claim | `tid` by default; confirm with provider |
| Email claim | `email` by default; must be verified |
| Email verification claim | `email_verified` by default |
| Display-name claim | `name` by default |
| Scopes | `openid email profile` |
| Provisioning | Invitation-only |
| Group-to-role mapping | Disabled |
| Application logout | WBS session revocation only |
| Provider single logout | Not approved / not implemented |
| Provider deactivation | Existing WBS sessions require operator revocation or natural expiry |

## Secret References

Record secret-manager object names, owners, rotation dates, and expiry alerts for:

- `OIDC_CLIENT_SECRET`;
- `OIDC_STATE_SECRET` (independent from JWT and audit secrets);
- `AUTH_JWT_SECRET`;
- `AUTH_AUDIT_SECRET`.

Never record secret material, authorization codes, provider tokens, state, nonce, or PKCE verifier.

## Provider Checks

1. Register exactly one callback per deployed API environment.
2. Disable implicit and hybrid grants; enable Authorization Code only.
3. Confirm S256 PKCE support and confidential-client authentication.
4. Confirm the provider issues `sub`, directory, email, verification, nonce, `iat`, and `exp` claims.
5. Confirm signing-key rotation publishes overlapping JWKS keys.
6. Confirm email aliases and mutable usernames do not replace `sub` as the immutable key.
7. Reject wildcard redirect/logout URIs.
8. Review provider group overage behavior even though groups do not grant WBS access.
9. Approve the maximum refresh-session window after provider deactivation and document the operator
   revocation SLA. Shorten `AUTH_REFRESH_TOKEN_DAYS` for higher-risk environments.
10. Configure every load balancer, CDN, proxy, APM, and web server to omit query strings for the SSO
    callback. The repository's application and reference Nginx configuration already log paths only.

Approval requires identity, application security, platform, and WBS product owners.
