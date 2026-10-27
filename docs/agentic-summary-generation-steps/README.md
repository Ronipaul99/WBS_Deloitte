# Agentic summary implementation steps

Status: Steps 1-4 independent local implementation verified, external qualification
pending, 2026-10-27. Step 2 still needs disposable PostgreSQL verification; Step 3
also needs PostgreSQL/runtime and live TLS qualification; Step 4 needs actual provider
and worker-path qualification. Step 5 now has a local orchestration foundation,
with PostgreSQL and worker integration still pending. Step 6 now has local
management APIs/UI and document-free worker-test persistence, with PostgreSQL
and live-worker qualification pending. Step 7 has local pinned evidence,
inventory/coverage, budgeting and tool primitives; PostgreSQL/current-run/worker
qualification remains pending. Step 8 has local analyst/controller, canonical
extraction, stable registers and bounded gap continuations; PostgreSQL, live quality
and worker qualification remain pending. Steps 9-15 remain planned;
no live provider has been configured here by these implementation steps.
See [Step 1 evidence](step-01-artifacts/implementation-evidence.md).
See [Step 2 evidence](step-02-artifacts/implementation-evidence.md).
See [Step 3 evidence](step-03-artifacts/implementation-evidence.md).
See [Step 4 evidence](step-04-artifacts/implementation-evidence.md).
See [Step 5 evidence](step-05-artifacts/implementation-evidence.md).
See [Step 6 evidence](step-06-artifacts/implementation-evidence.md).
See [Step 7 evidence](step-07-artifacts/implementation-evidence.md).
See [Step 8 evidence](step-08-artifacts/implementation-evidence.md).

This directory expands the [master plan](../agentic-summary-generation-plan.md)
into individually executable steps. Start with Step 1 and follow the dependencies.
The deliverable is a grounded, editable tender/RFP summary, generated through a
UI-selected provider and approved by a human. WBS and validation agents are later work.

## Decisions that apply to every step

- Tenant admins manage connections/keys; authorized editors select approved profiles.
- Implement OpenAI, Claude, and custom OpenAI-compatible adapters. Qualify OpenAI
  and the Mac-hosted Llama 8B gateway for the first demo. The Mac gateway is public;
  its protocol, authentication, limits, and model identifier remain external inputs.
- Keep keys server-side, encrypted and absent from prompts, browser bundles, jobs,
  checkpoints, ordinary logs, test fixtures, and committed evidence.
- Keep existing BGE embeddings, 384-dimensional pgvector storage, S3, Redis,
  Celery, document scope, and human approval. Generation models are independent
  of embedding models; selecting a different LLM does not re-ingest documents.
- Read all source sections for coverage; use scoped hybrid retrieval to fill gaps.
- Pin the processing run, model-profile version, schema, workflow, and prompts.
- LangGraph controls the agent graph; application contracts and SQL state remain
  provider-independent. Verify the tenant-scoped checkpointer before adopting it.
- Use the existing model-enabled worker with one processing slot for the demo.
  Agents are roles, not separate model processes or new always-on servers.
- Keep the feature disabled until the required end-to-end checks pass. Fake
  providers belong in tests only; missing configuration must never return a
  successful placeholder summary.
- Do not implement Oracle Document Understanding, new embedding models, WBS
  generation, or WBS semantic validation as part of these summary steps.

## Execution order

| Step | Document | Depends on | Deliverable |
| --- | --- | --- | --- |
| 1 | [Contracts and capability qualification](step-01-contracts-capability-qualification.md) | Master plan | Typed contracts and provider/checkpointer qualification plan |
| 2 | [Persistence, migrations, and permissions](step-02-persistence-permissions.md) | 1 | Scoped records, revisions, constraints, and permission matrix |
| 3 | [Credentials and endpoint security](step-03-credentials-endpoint-security.md) | 1-2 | Encrypted credentials and approved egress |
| 4 | [Provider adapters and capability tests](step-04-provider-adapters.md) | 1-3 | Common OpenAI/Claude/compatible inference interface |
| 5 | [Durable orchestration foundation](step-05-durable-orchestration.md) | 1-4 | Outbox, checkpoints, leases, retries, cancellation |
| 6 | [Model management APIs and admin UI](step-06-model-management-ui.md) | 2-5 | Connections, profiles, tests, and approved-model catalog |
| 7 | [Pinned evidence and coverage](step-07-pinned-evidence-coverage.md) | 1-6 | Source inventory, reading batches, scoped tools |
| 8 | [Evidence analyst and fact consolidation](step-08-evidence-analyst.md) | 4-7 | Supported facts and stable requirements |
| 9 | [Structured summary writer](step-09-summary-writer.md) | 7-8 | Typed tender draft with source-linked claims |
| 10 | [Verification and bounded repair](step-10-verification-repair.md) | 8-9 | Citation/fact checks and quality decisions |
| 11 | [Summary APIs, revisions, and approval](step-11-summary-apis-approval.md) | 2, 5-10 | Real summary jobs and revision-specific review contracts |
| 12 | [Summary UI and evidence review](step-12-summary-review-ui.md) | 6, 11 | Profile selection, truthful progress, citations, stable edits |
| 13 | [Lifecycle, limits, and observability](step-13-lifecycle-observability.md) | 5-12 | Deletion/recovery integration and operational controls |
| 14 | [Evaluation and regression checks](step-14-evaluation-regression.md) | 1-13 | Provider-specific quality and reliability evidence |
| 15 | [Deployment and demo verification](step-15-deployment-demo.md) | 1-14 | Verified ARM64 deployment, recovery, and two-provider demo |

Each step names proposed new files; those paths are implementation targets, not
claims that files already exist. Adapt placement to repository conventions while
preserving the contracts. Unit tests in earlier steps may use test doubles;
provider qualification and deployment gates must eventually use the real service.
Missing external credentials do not prevent building contracts and fake-provider
tests, but must remain recorded as pending before enabling that provider.

## Completion rules

For each step, satisfy prerequisites, implement the tasks, run its targeted tests,
and record the outcome and unresolved inputs. Complete dependency checks before
starting dependent implementation. Do not edit application code or deploy merely
because these documents were created.

Suggested evidence when implementation begins:

```text
step-NN-artifacts/
  implementation-evidence.md
  test-results.md
  remaining-inputs.md
```

Record versions, sanitized pass/fail summaries, and metric definitions. Keep real
keys, private document text, raw model requests/responses, customer identifiers,
and signed object URLs outside Git. Use ignored local artifacts when required.
Do not create populated evidence folders or mark steps complete in advance.

The earlier 85% Recall@5 gate measures retrieval only. Step 14 defines a separate
proposed summary-quality target that must be reviewed after the pilot. Never
show that retrieval score, or an LLM's self-rating, as summary confidence.

The [future WBS/validation roadmap](future-wbs-validation-roadmap.md) describes
extension points; it is not a sixteenth requirement for the summary release.
