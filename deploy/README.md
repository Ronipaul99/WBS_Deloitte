# Production Deployment References

The files in this directory are reviewed reference inputs, not a ready-to-run production stack.
Hosting, DNS, TLS, secret manager, WAF, telemetry backend, and Neon projects must be selected before
they can become platform-specific manifests.

- `production.env.example` is a value inventory. Secret values belong in the chosen secret manager.
- `edge/nginx.conf.example` shows HTTPS redirect, HSTS, proxy-header replacement, request limits,
  metrics isolation, and risk-based rate limits. Replace every example hostname, CIDR, certificate
  path, and upstream before use.
- The API and UI Dockerfiles build non-root immutable runtime images. Build the UI with
  `VITE_API_URL=https://<api-host>/api/v1`; run it with `API_ORIGIN=https://<api-host>` so the CSP
  and compiled API destination agree. The image build/runtime reject missing or non-HTTPS public
  API values.
- For enterprise SSO, build the UI with matching `VITE_AUTH_MODE`, `VITE_SSO_ENABLED`, and approved
  provider label values. Register the API callback, not the UI completion path, with the provider.
  Review the Phase 9 provider inventory and runbook before changing from `hybrid` to `oidc`.

Production promotion is governed by the Phase 8 deployment and incident runbooks under
`docs/authentication-authorization-phases/phase-08-artifacts/`.
