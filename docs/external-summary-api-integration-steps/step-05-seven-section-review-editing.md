# Step 5: Seven-section UI mapping, citations and draft editing

Status: planned. Depends on Step 3's progress/readiness behavior and Step 4's structured summary read/import contracts.

Read the [index](README.md), [master plan](../external-summary-api-integration-plan.md), preceding contracts/artifacts and current review/save/approval behavior first.

## 1. Objective

Use the existing summary review design to display all seven external sections, their evidence and truthful metadata. Save edited drafts by stable section identity with optimistic concurrency, preserving original generated provenance and existing human approval semantics.

This step does not create another summary generator, evidence-analysis agent, review redesign or WBS engine.

## 2. Inspect the current implementation

Inspect:

- `ReviewProjectSummaryScreen.tsx` and its CSS/components.
- `summariesApi.ts`, `workflowTypes.ts`, `workflowPresentation.ts`.
- Current `presentSummary`, hard-coded confidence, numeric section IDs and `summaryUpdateFromSections` positional mapping.
- Backend summary GET/PATCH/approve schemas/routes and permission checks.
- Step 4 structured storage, original/generated provenance, summary revision and downstream readiness metadata.
- Existing frontend test fixtures, legacy summary editing and project/workflow navigation.

Do not assume the current three-section model can safely accept seven external sections by changing labels only.

## 3. One presentation model with stable identity

Extend the existing representation through a discriminated legacy/structured branch rather than introducing a competing summary system.

For structured sections retain:

- Opaque string ID, stable category key and independent display order.
- Title, safe draft badge/subtitle, content and validated per-section edit limit.
- Answer status, source-reference label/pages, truncation warning and citations.
- Original-generated versus current-reviewed content state.

Selection and save use IDs/keys, never list position or display numbering. Reordered sections must retain edits and correct evidence. Duplicate/unknown identities are rejected by backend validation.

Expected categories:

| Key | Display heading |
| --- | --- |
| `project_overview` | Project Overview |
| `project_scope` | Project Scope |
| `key_deliverables` | Key Deliverables |
| `assumptions` | Assumptions |
| `constraints` | Constraints |
| `exclusions` | Exclusions |
| `milestones_timeline` | Milestones & Timeline |

Sort by validated order. Keep a legacy adapter for existing Overview/Key Points/Requirements summaries. Do not coerce external sections into numeric positions 1/2/3 or synthesize missing categories in the UI.

## 4. Map persisted data to existing elements

| Persisted structured field | UI behavior |
| --- | --- |
| Section title/order | Existing left navigation and active section heading/number. |
| Content | Existing text editor, preserving paragraph breaks and citation markers. |
| `max_length` | Section-specific count/limit validated by the backend. |
| Badge/subtitle | Plain-text AI Draft/editor copy under an application-owned authority policy. |
| Source label/pages | Existing Source References caption and page chips. |
| Citations | Accessible expandable rows with section-local number, quote and physical pages. |
| `answer_status` | Answered/Insufficient evidence or another supported explicit state. |
| Truncation flag | Review notice that retrieved evidence context was limited. |
| Document information | Filename, size and type checked against authoritative document identity. |
| Nullable confidence | Number only when recorded/valid; otherwise Not recorded, with no percentage bar. |
| Model/question-set/run | Supporting provenance details, not accuracy or approval claims. |

Remove the hard-coded 85% for this representation. Missing confidence is not zero, 85 or a placeholder percentage. Retain a clear explanation that drafts require review.

Treat service strings, source quotations and edited content as untrusted text. Do not render HTML, execute links/commands or accept a service-provided badge asserting approval. Reuse current style tokens/components and accessible loading/error patterns.

## 5. Citation behavior

1. Display numbers in their section namespace. Project Overview `[1]` cannot resolve to Project Scope `[1]`.
2. Keep chunk identity/provenance internally; the visible citation focuses on quote and physical page.
3. Link inline markers to their corresponding citation rows only when the contract resolves them exactly. Otherwise retain plain text and expose a clear unresolved marker state.
4. Do not treat existing page chips as a PDF navigation feature unless the current viewer explicitly supports it. Adding a new viewer is outside scope.
5. Show unknown/missing page information truthfully. Never infer pages from order, printed labels or filenames.
6. Preserve original generated evidence after editing. Label edited text as requiring review; an unchanged marker does not prove an edited claim is supported.
7. Do not re-run retrieval, call an LLM or change canonical citation data from the editor.

## 6. Structured draft save contract

Add the minimum authorized structured PATCH branch to the existing summary update API. Example logical request:

```json
{
  "format": "external_summary_v1",
  "expected_revision": 3,
  "sections": [
    {
      "id": "sec_1",
      "key": "project_overview",
      "content": "Human-reviewed draft text."
    }
  ]
}
```

This is an edit patch, not permission to replace evidence or provenance. Omitted sections preserve existing content. Duplicate entries, unknown IDs/keys, mismatched ID/key pairs and attempts to change tenant/document/run/job/model/citation metadata are rejected.

Backend behavior:

- Enforce the existing summary-update permission and trusted tenant/document scope independently of UI controls.
- Lock/guard the current summary revision and source eligibility in a short scoped transaction.
- Validate content against the persisted section's server-approved limit. The browser cannot raise it by sending another `max_length`.
- Preserve complete original content/citations and every untouched section.
- Advance revision once per actual accepted mutation, reset approval and maintain deterministic legacy projection.
- Update matching workflow revision/checkpoint metadata atomically with the save.
- Return authoritative structured content/revision; do not write edited content into the external job result.

Define no-op save behavior explicitly so it does not unexpectedly increment revisions or erase approval. A stale revision yields a safe conflict; do not silently last-write-win.

## 7. Editor state and limits

- Keep a saved baseline and current edits keyed by stable section identity.
- Switching sections preserves unsaved edits; switching document/tenant must clear them and abort old loads/saves.
- Warn before discarding unsaved edits using the existing pattern, without changing unrelated navigation.
- Show count/validation for the active section and accessible errors. Do not truncate imported content just because an HTML `maxLength` is smaller.
- Follow Step 4's over-limit policy: explicitly read-only/error until resolved, or a validated editing path that preserves all text. Never shorten silently on load/save.
- Clear success/error state appropriately; a save response for an old document cannot paint the new document's screen.
- On revision conflict, retain local text and offer refresh/review; do not auto-merge evidence/provenance or overwrite the server.
- Retry a read/save safely; never submit another generation request from editor error handling.

## 8. Approval and downstream compatibility

Retain explicit permission-controlled human approval. Imported content is always unapproved; user edits reset approval. The approve operation for structured summaries must check the current expected revision and source eligibility so a concurrent save cannot cause approval of unseen text.

Do not infer structured WBS requirements from numbered summary prose. Consume Step 4's downstream readiness/capability metadata:

- Legacy compatible summaries keep existing behavior.
- External summaries missing a valid downstream contract show a disabled/unavailable Generate WBS action with a clear reason.
- If separate approval already exists, preserve it. If approval is currently coupled to Generate WBS, implement only the narrow structured-summary approval action needed to retain review semantics without starting unsupported generation.

Do not implement requirement extraction, WBS generation/validation, or claim AI drafts are independently verified. A generation button cannot be enabled merely because seven sections exist or confidence is non-null.

## 9. Scope boundary

Allowed: existing review screen/types/presentation/client, its narrow styles, structured save/revision-safe approval contracts and corresponding tests. Reuse Step 4 storage; document any demonstrated minimal prerequisite extension.

Excluded: new summary generation prompts/agents, retrieval tools, general model administration, WBS algorithms, project/document dialog redesign, upload/deduplication changes and live environment changes.

Do not rewrite historical migrations. If review storage cannot preserve required data, document that gap and extend only the structured persistence boundary.

## 10. Verification and exit criteria

Use synthetic persisted summaries, not the user's tender text:

- All seven categories render in order with stable selection under reordering.
- Correct title/content/limit/page/citation/answer-status/truncation mapping.
- Null confidence, supported non-null confidence and no fabricated percentages/approval.
- Section-local citation collisions, unknown markers, unknown pages, multiline/Unicode/HTML-looking text.
- Partial patches preserve untouched sections/evidence; forged provenance and raised limits are denied.
- Save/reload/resume round trip, expected-revision conflict, concurrent save/approval and rejected stale response.
- Editing does not mutate `jobs.result_payload`; import replay cannot overwrite edits.
- Viewer/read-only permissions, cross-tenant IDs, keyboard navigation, accessible errors and mobile layout.
- Legacy three-section summaries and existing project/upload/document dialogs remain compatible.
- Unsupported external WBS generation is truthful, while legacy compatible generation remains unchanged.

Run focused backend save/approval tests with isolated fixtures, frontend/browser tests, TypeScript/build/lint and relevant Steps 1-4 regressions. Record results/screenshots/API semantics under `step-05-artifacts/`.

**Exit:** the seven-section draft is displayed and saved losslessly with evidence and concurrency protection; confidence/gaps are truthful; approval remains human-controlled; no new WBS engine or unrelated screen changes are introduced.
