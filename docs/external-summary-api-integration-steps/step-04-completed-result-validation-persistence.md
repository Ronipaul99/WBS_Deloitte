# Step 4: Completed-result validation and persistence

Status: planned. Depends on Steps 1-2 verified request/job binding and pinned source identity. Durable import must work without Step 3's browser staying open.

Read the [index](README.md), [master plan](../external-summary-api-integration-plan.md), preceding contracts/artifacts and current summary, chunk, lifecycle, transaction and migration conventions first.

## 1. Objective

Consume a confirmed completed `DOCUMENT_SUMMERIZATION` job's `result_payload`, validate its structure/scope/source provenance, and atomically persist a reviewable unapproved draft. Repeated reconciliation must not create another revision or overwrite later user work.

This step implements import and structured read contracts, not the seven-section editor or another generation engine.

## 2. Completion and read admission

Require all of the following before result loading:

- Step 2's exact acknowledged job passes tenant/project/document/type predicates.
- Status matches a qualified completed wire value and progress is exactly 100.
- Request identity, fence and expected source run remain valid.
- Document/project lifecycle and current authorization allow import.
- This request has not already imported a result or been superseded/abandoned.

Load only that row's `result_payload` through a bounded repository operation. Bound stored JSON size before full application deserialization where PostgreSQL permits; apply model/string/array/total-byte limits after loading as well. Do not include payloads in routine progress reads or logs.

If remote completion precedes payload visibility, persist an explicit import-pending state with a bounded grace period. Re-read the same job; do not call the external API or follow `result_url`.

## 3. Versioned result contracts

Define bounded schemas matching the supplied shape:

| Level | Required content |
| --- | --- |
| Envelope | `status`, bounded `message`, `data`; only a confirmed success envelope is accepted. |
| Data | Project/document/processing-run UUIDs, document information, sections, question-set ID and model label. |
| Document information | Filename, display size/type, nullable extraction confidence and confidence explanation. |
| Section | ID, order, stable key, title, badge, subtitle, content, max length, source references, question ID, answer status, truncation flag, citations. |
| Source references | Bounded label and positive physical page numbers. |
| Citation | Chunk UUID, quote, positive section-local citation number and positive physical pages. |

Required category keys:

```text
project_overview
project_scope
key_deliverables
assumptions
constraints
exclusions
milestones_timeline
```

Validate unique section IDs/keys/order, expected category completeness, known answer-status values, content/quote/list bounds, numeric confidence range when non-null and internally valid citation numbering. `[1]` is local to its section; the same number in another section is not a collision.

Missing/extra categories require an explicit schema-version compatibility decision. Do not silently omit them or fill missing sections with fabricated content. An insufficient-evidence answer with no citations can be valid if the contract permits it.

Maintain separate import-size and edit limits: content over an advertised editable limit must not be truncated. Reject unsupported payload bounds, or preserve an explicitly flagged read-only over-limit section under a documented policy. Step 5 must enforce the same policy.

## 4. Validate ownership and provenance

1. Compare result document/project IDs to the trusted request, not browser fields or filenames.
2. Compare returned processing-run ID to the pinned completed run; verify run ownership and source compatibility.
3. Revalidate source/run lifecycle and activation before accepting content. The remote API accepts document ID only, so source changes during remote execution must be detected here.
4. Batch-check citation chunk ownership against the exact tenant/project/document/run with explicit predicates and RLS.
5. Validate quotes against canonical stored chunk text using a documented exact/normalization policy and available page metadata. Reject foreign chunks, altered unsupported quotes and invented page precision. Do not normalize so loosely that different claims become accepted.
6. Keep physical pages separate from printed labels. Do not infer pages from section order or approximate retrieval ranking.
7. Preserve null confidence, answer status, truncation warnings, model/question-set/run identities and original citation data.

If upstream quotes use undocumented normalization or a citation lacks required canonical metadata, return a specific compatibility/validation failure or explicitly non-verified state according to the approved contract. Do not label citations verified merely because a chunk UUID exists.

This is structural/canonical provenance validation, not independent semantic entailment, factual verification or approval. No new LLM calls, embedding downloads or private PDF fetches are needed.

## 5. Minimal structured review persistence

Inspect current summary storage first. Preserve the one-row-per-document `DocumentSummary`, its legacy columns and existing review semantics.

Add only the demonstrated storage gap, for example:

- Versioned structured summary JSON with all sections, source metadata and original generated content.
- A scoped source-request reference, giving external job/run/model/question-set provenance.
- Imported result digest and import identity in the Step 1 request record.
- Existing summary revision/approval fields remain authoritative; expose revision in the response for Step 5 optimistic editing.

Use scoped foreign keys/constraints and RLS. If schema changes are needed, create a narrow additive migration from the actual current head. Never rewrite earlier migrations or migrate the application database during verification.

The generated `jobs.result_payload` stays unchanged. User edits belong in review storage. Do not replace the job payload with the local summary ID or embed secrets/raw provider conversations into review data.

## 6. Atomic import algorithm

1. Claim/import-admit the request using its existing lease/fence and pinned input identity.
2. Read and validate bounded input outside long-held write locks. Capture a stable result hash; reject changes during the acceptance transaction rather than publishing a mixed snapshot.
3. Begin a short scoped transaction and lock the request/current summary/workflow rows in a documented consistent order.
4. Recheck fence, source/run eligibility, current attempt, expected summary revision and whether this result was already imported.
5. If the request/result is already imported, return the existing identity without touching revision, edits or approval.
6. If a later attempt or human edit/approval superseded the expected revision, mark the import stale/conflicted. Never overwrite it silently.
7. Create/update the review row with validated structured content and deterministic compatibility projection; set `is_approved=false`, clear approval time and advance revision exactly once.
8. Update only matching authorized workflow associations, summary ID/revision and checkpoint state. Preserve historical generated workflow lineage.
9. Store request imported marker, result hash and summary identity/revision in the same transaction.
10. Commit. A rollback leaves no partial review-ready state and can safely reconcile the same result later.

Independent worker/reconciliation hooks must complete this process after browser closure. Status GET can observe import state; it must not be the sole mechanism for progress or trigger a new remote submission.

## 7. Legacy projection and downstream boundary

- Render all ordered section titles/content deterministically into legacy `summary_text` within explicit compatibility bounds.
- The response contains no structured requirements register. Do not turn arbitrary numbered sentences into verified `REQ-*` items or invent missing values.
- Populate legacy key points/requirements only where a documented faithful mapping exists. Preserve older compatible summaries and define replacement policy explicitly.
- Keep structured data lossless regardless of the compatibility projection.
- Report downstream WBS readiness honestly. If the new payload cannot satisfy the existing generation contract, expose an unavailable capability/reason; deriving WBS-ready requirements is outside this integration.

No WBS worker, summary analyst/writer/verifier, agent graph or semantic approval gate is implemented here.

## 8. Result-read API handoff

Extend the existing authorized summary GET response with a discriminated structured branch or compatible additive fields:

- Summary ID/document/tenant identity and authoritative revision/approval state.
- Versioned sections/document information and provenance.
- Original generated citation metadata versus current reviewed/edited content state.
- Readiness/capability metadata needed to avoid unsupported downstream actions.

Legacy summaries remain readable through their existing representation. Step 5 uses this API; it must not read `jobs.result_payload` directly in the browser or reconstruct the import independently.

## 9. Verification and evidence

Use synthetic result fixtures and isolated storage:

- Valid seven-section result and exact scope/run/canonical citations.
- Failure envelope, missing data, duplicate keys/IDs/orders, malformed values and payload bounds.
- Null confidence, insufficient evidence, truncation flags, Unicode/multiline content and section-local citation numbers.
- Foreign project/document/run/chunk, wrong hash/quote/page, changed active source and deletion during validation.
- Completed-at-80, running-at-100, delayed/missing result and result mutation between validation/commit.
- Import twice, competing importers, stale fences, later edits/approval and superseding attempts.
- Fault injection before/after summary write, workflow update and imported marker; no partial commit.
- Lossless structured/legacy reads without fabricated requirements or changed external job payload.

Run disposable PostgreSQL migration/RLS/locking/rollback checks where available; preserve legacy summary and ingestion compatibility fixtures. Run focused tests, Steps 1-2 regressions, lint and diff checks. Record results/schema decisions under `step-04-artifacts/`.

**Exit:** valid completed results become one saved unapproved draft with exact provenance; duplicate/stale imports are safe; read contracts support Step 5. Remote generation success, local import success and human approval remain distinct.
