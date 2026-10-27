# Step 14: Evaluate summary quality and run regression checks

Status: planned. Depends on Steps 1-13.
Previous: [Step 13](step-13-lifecycle-observability.md).
Next: [Step 15](step-15-deployment-demo.md).

## Objective

Measure factual support, omissions and operational reliability separately for
OpenAI and the actual Mac-hosted Llama 8B. Retrieval accuracy is not summary accuracy.

## Implementation tasks

1. Create a source-grounded gold set for the supplied tender plus a different tender
   and synthetic fixtures. Annotate facts, accepted paraphrases, source spans/pages,
   conditions, alternative values, criticality and explicitly unanswerable fields.
   Use held-out documents/paraphrases to reduce tuning to one familiar PDF.
2. Include issuer, total/per-unit capacity, initial proposal unit counts, PPA term,
   both EMD options, eligibility, dates, evaluation/award rules, annexes, table
   continuity, missing facts, contradictory clauses and document-instruction attacks.
3. Run the same pinned input/schema/workflow/prompts with each qualified demo
   profile. Record model/profile/capability versions and settings; compare output
   quality and measured resources, not provider marketing/context claims.
4. Measure required-fact coverage as correctly stated and cited annotated facts
   divided by applicable annotated facts. Report critical and overall results,
   citation locator validity, human-judged entailment, invented assertions,
   omissions, contradictions, unresolved fields and schema failures separately.
5. Measure wall time, queue/provider latency, call counts, tokens/unknown usage,
   retries, repairs, cost estimates/actuals and peak worker RSS. Account for the
   many reading calls a long RFP requires; do not silently reduce source coverage
   to make the demo appear faster.
6. Run deterministic unit/API/UI tests, disposable PostgreSQL RLS/migration/replay
   tests and fault injection. Live-provider tests are small explicitly configured
   runs outside ordinary CI; fixtures/fake providers cannot establish live quality.
7. Publish sanitized aggregate evidence and residual misses. Keep PDFs, extracted
   text, model responses, credentials and signed source URLs in ignored private
   artifacts. Capture evidence definitions so a percentage can be reproduced.

## Proposed release checks

| Measure | Gate |
| --- | --- |
| Citation identifiers/locators on published claims | All valid and in pinned scope |
| Unsupported critical financial/date/capacity assertions | None presented as verified |
| Source coverage | Every primary chunk accounted for; partial output explicitly blocked from downstream-ready approval |
| Required-fact quality | Proposed initial target: at least 85% correctly stated and cited for each demo provider |
| Permissions/replay/lifecycle | All applicable regression and fault tests pass |
| Resources | Worker stays within measured safe limits and the API remains responsive |

The 85% summary target is proposed and must be reviewed after the pilot. It is
not already approved by the earlier 85% Recall@5 waiver. A score must not conceal
a critical invented amount or missing condition. Document remaining misses and
whether a model can be enabled for the intended demo workflow.

## Proposed implementation targets

- An evaluation script under `backend/scripts/`, synthetic gold fixtures and tests.
- A private gold dataset/output directory under ignored `backend/.data/`.
- UI integration tests and sanitized step evidence with a provider comparison table.

## Verification commands

After adding the named test modules, run their targeted tests first, then the
backend suite and relevant PostgreSQL integration harness. Use only disposable
databases for destructive harness setup/teardown. Frontend checks include:

```powershell
cd WBS_UI
npm.cmd run lint
npm.cmd run build
```

Run the appropriate Playwright workflow tests against test instances. Do not point
normal CI at the demo tenant, a real paid provider, or uploaded private PDFs.

## Exit criteria

- [ ] OpenAI and actual Mac Llama results have separately reproducible measurements.
- [ ] Quality definitions/targets and residual misses are reviewed and recorded.
- [ ] Security, reliability, lifecycle, database and UI regressions pass.
- [ ] No fabricated confidence or unqualified general accuracy claim accompanies the demo.
- [ ] Remaining external/provider gates are explicit before deployment enablement.
