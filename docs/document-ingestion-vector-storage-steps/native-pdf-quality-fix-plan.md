# Native PDF extraction, chunking, and retrieval improvement plan

Status: completed, deployed and live-audited on 2026-10-27 against the
user-approved 85% relevance target. Results and operating commands are below.

## Objective and scope

Preserve the headings, clause context, glossary definitions, and table
relationships in native text PDFs; remove page-margin noise; improve retrieval
without weakening the existing vector integrity or tenant isolation guarantees.

The audited baseline is `RFP_FSPV_UI_225MW.pdf`: 110 physical pages, 4,055
extracted blocks, 161 correctly persisted 384-dimensional vectors. Its database
document ID is `d527cb62-934d-45f7-b992-172bf68280d6`, and its baseline run is
`dca425e8-c0e5-4a95-be9f-39675870ec6e`.

Keep the current BGE model, 384 dimensions, pinned tokenizer/model artifacts,
S3, Neon, malware scanning, and worker isolation. Scanned/image-only PDF OCR and
automatic retention/deletion remain outside this work. Chunk count may change;
preserving the current 161 chunks is not an acceptance requirement.

## 1. Establish a reproducible quality baseline

- Build an evaluation harness that reads the supplied PDF and produces candidate
  extraction/chunking artifacts without submitting tasks or writing database rows.
- Record source hash, extractor/chunker identity, tokenizer/model pins, policy
  values, removed-margin spans, source coverage, timings, and peak memory.
- Create a source-grounded set of approximately 20 questions covering capacity,
  location, glossary definitions, PPA term, EMD options, validity periods, clauses,
  and annexes. Label relevant source spans/pages rather than current chunk IDs.
- Separate development questions from held-out paraphrases. Include unanswerable
  questions so returning a nearby vector is not mistaken for finding an answer.
- Retain the current output as the baseline. Use small synthetic PDF fixtures in
  CI; keep the supplied document and extracted business content out of Git.

Initial hard cases: the PPA-duration answer currently ranks ninth for the long
question and fourth for the acronym question. The EMD table is split between
current ordinals 47 and 48. These ordinals will change after reprocessing.

## 2. Correct margin handling and recover PDF structure

Primary implementation area: `backend/app/services/ingestion/extractors/pdf.py`.
Add a separate layout adapter module if needed to keep parsing and policy clear.

### Margin cleanup

- Group candidate margins by normalized pattern, so changing numeric values in
  `Page N of M` do not prevent repetition detection.
- Require margin position and consistent multi-page evidence before removal.
  Preserve page references and account explicitly for every removed span.
- Do not remove matching phrases from body paragraphs or table cells.

### Headings and clauses

- Use bounded layout evidence such as font size/style, position, numbering, and
  reading order to identify section, part, clause, and annex headings.
- Propagate a bounded `heading_path` to following blocks; avoid treating glossary
  terms and table cell labels as document-wide headings.
- Preserve physical PDF page numbers for citations; distinguish printed page
  labels when available rather than shifting physical references.

### Tables and glossary definitions

- Prototype a bounded layout/table reader on the ruled glossary and EMD tables
  before selecting a dependency. If an additional parser is needed, verify its
  ARM64 build, deterministic output, and resource usage before pinning it in the
  worker build and updating packaging/readiness checks.
- Emit existing `TABLE_ROW` blocks with explicit table identity, header metadata,
  cell order, row identity, page references, and heading context.
- Preserve each glossary term together with its definition. Handle continued
  rows and repeated headers across pages conservatively.
- Reconcile table regions with surrounding text to prevent duplicate extraction
  or silently omitted text. Ambiguous layouts must retain text with a stable
  warning instead of inventing cell relationships.
- Keep the existing parser deadlines, byte/page/block limits, private processing
  workspace, and malware scanning boundary.

Acceptance: all substantive source text is covered; only recorded, validated
margin spans are excluded. Headings are populated where identifiable, and the EMD
options remain correctly paired with their amounts.

## 3. Use the existing structure-aware chunker

Primary implementation area: `backend/app/services/ingestion/chunking.py`.
The existing chunker already supports table rows, table header context, and
heading-based grouping; connect the improved PDF blocks to those capabilities
before changing chunking algorithms.

- Keep rows intact when they fit the token bound. For oversized rows, repeat
  column labels and row identity on each bounded fragment.
- Repeat table headers in table continuation chunks. Avoid overlap that crosses
  unrelated sections, tables, or glossary entries.
- Verify that headings are carried into retrievable context. If formatting the
  embedding input changes, version that formatting policy explicitly.
- Preserve primary/overlap/header source roles and deterministic canonical hashes.
  Retain the current 400-token target, 50-token overlap bound, and 480-token ceiling
  initially; tune only if evaluation shows a reason.

Tests should cover long rows, multi-page tables, genuine repeated body text,
heading transitions, paragraph continuation, and exact source coverage.

## 4. Improve retrieval and measure it

Current code provides `VectorPersistenceRepository.exact_active_similarity`;
there is no existing public content-search endpoint to modify. Add a scoped
internal retrieval service and evaluation harness around this repository first.
Wire it into an actual application consumer only when that consumer is identified.

- Retrieve bounded semantic candidates and lexical candidates from the same
  permitted tenant/project/document and active completed processing run.
- Use PostgreSQL full-text search for lexical candidates, with a migration and
  GIN index if materialized search text is selected. Evaluate heading and glossary
  context in search text; do not assume lexical fusion alone fixes the PPA case.
- Fuse candidate rankings deterministically, for example with reciprocal-rank
  fusion, deduplicate by chunk identity, and evaluate final top-five relevance.
- Start evaluation with approximately 20-30 candidates per retriever. These are
  bounded tuning values, not promised production settings.
- If hybrid retrieval does not meet the acceptance gates, benchmark a pinned
  CPU-capable reranker. Add it only if it improves held-out relevance within the
  observed 1-CPU/~6-GB VM's memory and latency budget. Do not assume spare RAM or
  introduce a paid/external model service by default.
- Return source citations and scores; distinguish weak/no-evidence results rather
  than treating every nearest neighbour as an answer. Calibrate relevance handling
  with unanswerable examples rather than inventing a universal score threshold.

Tests must exercise scope filtering before candidate selection, inactive/failed
runs, deleted/hidden documents, deterministic ranking, and no cross-tenant results.

Accepted current-release relevance gate: the PPA-duration and acronym questions both return the
answer in the top five; each EMD option retrieves its correctly paired amount;
Recall@5 is at least 85% on the labelled set, with no regression on held-out
capacity/location questions. Report individual failures as well as the aggregate.

The user accepted 85% on 2026-10-27; the original 90% target is deferred. Oracle
Document Understanding is a future extraction improvement, explicitly outside
this rollout. No Oracle document-processing API or paid service is enabled here.

## 5. Version, deploy, and reprocess safely

- Bump the PDF extractor identity from 1.0.0 for changed extraction semantics.
  Bump chunker/embedding-format identities only if their behaviour changes.
- Update the actual implementation constants, `release_identity.py`, API
  completed-run matching, tests, and worker/API runtime identity consistently.
  Existing run uniqueness includes these identities, so the next request can
  create a new run instead of returning the previous completed job.
- Complete offline candidate extraction, chunking, embedding, coverage, and
  retrieval evaluation before invoking live reprocessing. The current ingestion
  orchestrator automatically activates a successfully processed run; it does not
  provide a shadow-run mode.
- Validate PostgreSQL migrations and retrieval isolation on a disposable database.
  Never point destructive integration fixtures at the user's Neon database.
- Rebuild and verify the ARM64 worker, update scheduler/API code where required,
  and run one document through the normal ingestion API. Re-embed the changed
  chunks and verify every stored vector, metadata record, and active-run pointer.
- Keep the previous completed run and vectors. Do not enable retention or delete
  historical rows as part of rollout. Test a scoped, validated rollback operation
  before cutover; a rollback must preserve lifecycle and tenant invariants rather
  than manually editing an active-run pointer.
- Re-audit the supplied PDF and compare source-grounded relevance and resource
  measurements against the saved baseline before considering broader reprocessing.

## Completion gates

1. All substantive source spans accounted for; no duplicate primary coverage.
2. EMD/glossary table relationships preserved; identifiable heading paths present.
3. Variable page footers removed without losing body content or citations.
4. Deterministic chunk hashes, bounded tokens, valid metadata, and reproducible
   finite 384-dimensional vectors for every new chunk.
5. Relevance gates above met, with measured CPU, peak memory, and latency reported.
6. Active-run isolation, lifecycle handling, tenant RLS, idempotency, activation,
   and rollback checks pass.

HNSW/IVFFlat is a later scaling decision. Exact pgvector search already works for
the current document; an ANN index would not fix missing headings, flattened
tables, or an irrelevant ranking. Add one only after corpus/latency measurements
justify it, then measure recall and filtered-search behaviour separately.

Suggested implementation sequence: baseline and footer tests; layout/table and
heading extraction; chunker integration and identity updates; retrieval evaluation
and improvements; disposable-database checks; one-document deployment and re-audit.

## Implemented behavior and validation

- PDF extractor and chunker identities are both `1.1.0`. Other extractors and the
  pinned 384-dimensional BGE embedding model/format are unchanged.
- The bounded pdfplumber adapter reconciles each candidate page against guarded
  pypdf text. Ambiguous coverage retains original text with `PDF_LAYOUT_FALLBACK`.
  Physical page numbers remain the citation coordinates. Printed footer labels
  are retained as removed-margin evidence, without shifting page references.
- Ruled tables retain ordered cells, table/row identity, headers and heading paths.
  Adjacent continued tables require matching geometry and section context.
  Glossary term context stays local to its row.
- Canonical chunks can repeat explicit glossary acronym definitions and table
  introductions as source context. These copies have `header_context` references;
  their original blocks retain primary ownership. They consume the same 480-token
  budget and participate in canonical hashes.
- Internal `HybridRetriever` collects 30 semantic and 30 lexical candidates from
  the permitted active, completed run, then deduplicates through reciprocal-rank
  fusion. Lexical expansion uses explicit, unambiguous glossary aliases from that
  same document/run. Migration `e71c4a9b203d` adds the matching GIN index.
- A worker-only, pinned quantized MiniLM cross encoder reranks at most 60 chunks
  on one CPU thread. Long passages use at most three source windows. Artifact
  downloads occur during image construction; runtime verifies every file hash.
  Results include source pages, headings and ranking scores, and remain explicitly
  `unverified_candidate`. Raw logits are not answer confidence. The two negative
  examples do not justify a general acceptance threshold or automatic answering.
- Rollback validates scope, lifecycle, current pointer, pending ingestion,
  completed identity, content hash, chunk continuity and vector validity under
  the document lock. It preserves both runs and all historical vectors.

The final local regression suite passed **558 tests**, with six integration tests
skipped in that invocation. Three PostgreSQL integration tests separately passed
on a uniquely named disposable database, including migration upgrade/downgrade,
RLS, activation concurrency, hybrid candidate scoping and deletion exclusion.
The disposable database was removed after validation.

Private evaluation material is under `backend/.data/pdf-quality-candidates/`,
which is excluded from Git. It contains source hashes, full candidate artifacts,
20 labelled answerable questions, two negatives, development/held-out splits,
per-question results and resource measurements. `label-corrections.json` records
one independently verified correction: the same maximum-two-unit award rule is
valid evidence on physical pages 15, 30 and 48, rather than page 15 alone.

The source candidate accounts for all 110 pages, 107 removed margin spans,
3,440 blocks, 239 table rows, 30 tables and 391 chunks. Candidate extraction,
chunking, embedding and the first reranker evaluation took 453.8 seconds with
peak RSS 1,375,028 KiB on the observed 1-CPU ARM VM. Final PostgreSQL retrieval
and live-run measurements are recorded after the rollout gate below.

## Operational verification and rollback

From `backend`, `python -m scripts.check_pdf_quality_postgres` creates its own
temporary database, runs migration/integration checks and removes only that
generated database. Do not manually point destructive fixtures at the application
database. This helper requires the local direct migration credentials; do not
copy migration-owner credentials into the worker.

The offline harness is `scripts/evaluate_native_pdf_quality.py`; pass `--input`,
`--output` and `--questions` inside the pinned worker environment. Its lexical
preview is labelled explicitly and does not substitute for PostgreSQL ranking.
`scripts/verify_pdf_quality_storage.py` audits actual active rows, independently
recomputes canonical hashes and embeddings, tests tenant isolation, and evaluates
the actual hybrid/reranker service. Supply explicit tenant, project, document,
question/output paths and `--previous-run` to verify retained baseline vectors.
Use `--candidate-artifact` to require an exact match with accepted offline chunk
hashes, and `--minimum-recall 0.85` for the approved current gate. Diagnostic
`--retrieval-only` and `--question-id` invocations identify skipped/partial checks
in their output and do not replace the full audit. Stream scripts to a separate
bounded worker-image container on the private Compose network, with the private
question/state mounts. This avoids adding another embedding model process to the
live Celery container's memory limit.

Use `scripts/restore_document_run.py` with explicit `--tenant`, `--project`,
`--document`, `--target-run` and `--expected-active-run`. Without `--apply` it
makes no change. A stale expected pointer, pending ingestion, deleted document,
wrong scope or invalid target fails closed. Restoring the previous image also
requires its matching API identity; keep the pre-rollout image tags until the
new run has passed the full re-audit. Retention and orphan repair remain disabled.

## Accepted rollout: 2026-10-27

- Migration head: `e71c4a9b203d`.
- Active run: `cdd197dd-809b-4070-9650-8b47239331e9`.
- Ingestion job: `aa8d2151-0002-43bd-b853-64e6ee648487`.
- The normal API completed ingestion in one attempt: 110 pages, 3,440 blocks,
  391 chunks, no error. Worker execution took 271.6 seconds.
- Duplicate requests during processing and after completion both returned the
  same job. No second reprocessing run was created.
- All 88 deployed application Python files match the local source hashes.
- Previous run: `dca425e8-c0e5-4a95-be9f-39675870ec6e`. All 161 previous chunk
  IDs, canonical hashes and stored vector components remain unchanged.
- The accepted disposable-PostgreSQL benchmark is **17/20 (85%) Recall@5**,
  compared with **15/20 (75%)** for saved baseline exact-cosine retrieval.
  Both PPA-duration questions, both EMD options, total capacity and location pass.
  The three remaining labelled-evidence misses are per-unit capacity, initial
  financial-proposal unit count and issuer. The development split is 9/10 and
  the held-out-labelled split is 8/10; this small document-specific evaluation
  does not establish general corpus accuracy.
- That full candidate audit independently reproduced every stored vector with
  maximum component error `2.80914306260982e-08`, verified every canonical hash,
  tenant isolation and all primary source blocks. It observed 390 chunks with
  heading paths, 239 referenced table rows and zero page-footer chunks.
- On one ARM CPU, median complete retrieval latency was 11.29 seconds and p95
  was 15.24 seconds over the 22 evaluation queries. Full candidate audit time
  was 483.8 seconds; peak RSS was 1,406,136 KiB (1.34 GiB). These are measured
  development-VM values, not interactive latency promises.
- Worker image: `sha256:89e247eaee2e428f8eb2ce922e181cd762ab628662b99720a3f8cfb16cc026d1`.
- Scheduler image: `sha256:9817561d83de8fb050112caf707c78e41dd74dc6c6a87086e408d91f1de30788`.
  Both use the verified dependency/model candidate as a base with the matching
  final application source. The checked-in Dockerfile also builds this source
  and pins the same model artifacts and dependencies. Pre-rollout image tags
  `wbs-ingestion-worker:pre-pdf-quality` and `wbs-background:pre-pdf-quality` remain.

The final live audit **passed**: all 391 stored chunk hashes match the offline
candidate; all 391 finite, normalized 384-dimensional vectors were independently
reproduced with maximum component error `2.80914306260982e-08`. Primary-block
coverage, metadata, tenant isolation and retained baseline vectors passed.
Live Recall@5 is **17/20 (85%)**. Both PPA questions and both EMD questions return
the labelled answer at **rank 1**. The same three documented misses remain.

Full live audit time was 486.7 seconds, peak RSS 1,431,176 KiB (1.36 GiB), median
retrieval 11.57 seconds and p95 14.66 seconds on one ARM CPU. Redis, ClamAV,
Celery worker and scheduler are healthy; `pip check` reports no broken
requirements. No broader corpus reprocessing was performed.

The follow-up report is
`backend/.data/audits/5662288b/quality-fix-report.md`, with full live JSON in
`quality-fix-live-audit.json` beside it and supporting private artifacts under
`backend/.data/pdf-quality-candidates/`.
Oracle Document Understanding remains deferred; this release adds no Oracle
document API credentials, SDK integration or paid inference service. Retrieval
is an internal service; no new public search endpoint or application consumer
has been introduced.
