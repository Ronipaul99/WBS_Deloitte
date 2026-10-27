# Future work: WBS generation and validation agents

Status: deferred design notes. This document is not part of the 15-step summary
release and does not authorize enabling placeholder WBS output.

Read the [summary step index](README.md) and complete the summary/review contracts
before implementing a separate WBS execution plan.

## Reusable foundation

Reuse tenant connections/profiles, adapters, scoped evidence tools, versioned graph
state, checkpoints, budgets, durable delivery, observability and human-review UI.
Keep workflow eligibility separate so a profile qualified for summary generation
is not automatically qualified for large WBS decomposition or semantic validation.

## WBS generation graph

1. Pin the approved, current summary revision, its requirement IDs/source run,
   project scope, selected template version and model-profile version.
2. Decompose supported scope into phases, deliverables and work packages.
3. Retrieve additional source evidence where the summary lacks necessary detail;
   the original document remains authoritative.
4. Mark inferred planning assumptions separately from source requirements. Never
   present invented effort, duration, resources or dependency estimates as tender facts.
5. Build requirement-to-work-package coverage and identify uncovered obligations.
6. Run structural checks, evidence review and bounded repair, then publish a
   distinct WBS revision for human review. Preserve upstream identity and approvals.

## Validation graph

Pin a WBS revision, approved requirements/source evidence and selected model
profile. Run deterministic checks for IDs, hierarchy, cycles, required fields
and coverage before model-based semantic analysis. Add an evidence-review agent
for omitted requirements, unsupported work packages, contradictions and risk.
Return typed findings/proposed corrections; an LLM cannot overrule deterministic
failures or edit an approved artifact without creating a new revision.

## Extension decisions for that phase

- Define WBS/validation output schemas and their own evaluation datasets/gates.
- Add explicit per-role model assignments only after the one-profile-per-run
  summary demo is stable; snapshot every assignment and aggregate its budget.
- Test stale-source/summary/template behavior, concurrent edits and approval races.
- Define how humans accept proposed corrections and how downstream approvals are invalidated.
- Review worker capacity before adding parallel agents or new model processes.
- Keep extraction upgrades, including Oracle Document Understanding, independently
  versioned so source changes trigger deliberate re-ingestion/revalidation.

Create numbered WBS/validation implementation documents when that work is requested;
do not mix it into unfinished summary steps.
