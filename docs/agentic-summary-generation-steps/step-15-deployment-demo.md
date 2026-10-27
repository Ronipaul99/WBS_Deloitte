# Step 15: Deploy and verify the two-provider summary demo

Status: planned. Depends on Steps 1-14.
Previous: [Step 14](step-14-evaluation-regression.md).
Later work: [WBS/validation roadmap](future-wbs-validation-roadmap.md).

## Objective

Deploy the completed summary feature to the existing Oracle VM and demonstrate
the same document through Mac Llama and OpenAI with real evidence and recovery.

## Deployment prerequisites

- Step 14 evidence and unresolved external inputs are recorded.
- The Mac gateway is reachable by the worker over authenticated HTTPS; its exact
  protocol/model/profile is qualified. OpenAI credentials/model access and a demo
  call/token/cost budget are available through a secure channel.
- Encryption keys are provisioned independently of the DB, with tested recovery.
  No real key is copied into examples, a UI build argument or source control.
- Image versions, migration compatibility and prior service images are recorded.
  Deploy only within the authorization for the implementation/release task.

## Implementation and rollout sequence

1. Package and pin orchestration/provider dependencies in reviewed ARM64 images.
   Keep BGE/reranker artifacts and versions intact. Keep model loading out of the
   API process; Llama inference remains on the Mac. Verify image dependencies and
   offline retrieval/model readiness before changing running services.
2. Add the disabled feature flag and required secret references to runtime
   configuration. Mount encryption-key material read-only into only the processes
   that need it. Do not copy database-owner credentials into API/worker containers.
3. Back up the database/key material using the existing authorized operational path.
   Apply the new migration through the migration role. Verify runtime permissions,
   RLS, schema head, legacy summary reads and compatibility before enabling traffic.
4. Deploy compatible API/worker/scheduler code with agentic summaries still disabled.
   Update the existing Beat schedule for workflow reconciliation; do not start a
   second Beat instance. Preserve Redis/ClamAV/S3 and current HTTPS behavior.
5. Deploy the UI with the settings, model selector and summary review changes. Keep
   `/api/v1` on the existing same-origin domain. Do not add browser provider keys,
   publish model/broker ports, or change endpoint policy to bypass a failed gateway.
6. As tenant admin, create/test the Mac and OpenAI connections and model profiles,
   select a default, configure limits, and verify editor/viewer permissions. Qualify
   Claude independently before enabling it. Test missing-key/decryption failure safely.
7. Enable the feature for the demo scope, verify readiness, and run the checklist
   below. Record real model/profile IDs and sanitized outcomes. WBS actions remain
   unavailable until their separate implementation is complete.
8. Verify restart/resume and rollback procedures. Disabling the feature prevents new
   work without destroying prior revisions or provider settings. Preserve old
   image versions and new-schema compatibility; do not routinely downgrade a live
   database or remove its encryption key as an application rollback.

## Existing deployment entry points

The current web checkout is `/home/developer/wbs-web`; its HTTPS wrapper is
`deploy/oracle/web-compose.sh`. Background services currently use the separate
`/home/developer/wbs-services` checkout and `compose.services.yml`. Keep source,
image, configuration and task compatibility across both checkouts; deploying only
the web checkout does not update the ingestion/model worker automatically.

Adapt build commands to the implemented packaging and recorded image tags. Read-only
verification examples after deployment:

```bash
cd /home/developer/wbs-web/deploy/oracle
sh web-compose.sh ps
curl -f https://wbsgenie.duckdns.org/api/v1/health/ready
systemctl list-timers --all wbs-tls-renew.timer
```

Use the existing ingestion-worker build helper when that image changes; preserve
its pinned model/OCR inventory and confirm worker health after replacement.

## Demo acceptance checklist

- [ ] Admin can manage/test providers; editor can choose them but cannot read keys.
- [ ] Viewer cannot start inference or mutate summaries.
- [ ] Generate through Mac Llama: truthful progress, complete source coverage, typed draft.
- [ ] Open citations for capacity, issuer, PPA duration and each EMD option.
- [ ] Inspect missing/conflicting information and actual model/usage provenance.
- [ ] Regenerate through OpenAI: distinct run/revision with preserved prior history.
- [ ] Edit one requirement, confirm its ID/evidence behavior, and approve the exact revision.
- [ ] Old/stale/deleting input, invalid citations and partial coverage cannot pass approval.
- [ ] Provider outage does not silently switch providers or return placeholder success.
- [ ] Cancellation/worker restart does not publish a late or duplicate revision.
- [ ] Summary and ingestion stay within measured resource limits; existing services stay healthy.
- [ ] API keys/prompts/signed URLs are absent from ordinary logs and browser storage.
- [ ] WBS generation remains visibly and server-side deferred.

## Exit criteria

The summary release is complete only when repository checks and the actual
Mac/OpenAI demo both pass with recorded evidence. Unavailable credentials,
unreachable gateway or unmet quality/resource gates remain explicit limitations;
do not substitute canned output to claim completion. No other hosted-service
migration or WBS implementation is required by this step.
