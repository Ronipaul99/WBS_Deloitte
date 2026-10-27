# Step 10: Verify evidence and implement bounded repair

Status: planned. Depends on Steps 8-9.
Previous: [Step 9](step-09-summary-writer.md).
Next: [Step 11](step-11-summary-apis-approval.md).

## Objective

Distinguish well-formed output from supported output, catch critical mistakes,
and keep unverified or incomplete information visible to human reviewers.

## Implementation tasks

1. Validate every citation deterministically: tenant/document/run/chunk relation,
   canonical hash, quote/range, physical page bounds, table row references and
   existence of all claim/evidence IDs. Recheck lifecycle and pinned run identity.
2. Add typed checks for amount/currency/unit/date/range/condition relationships.
   Preserve original source values alongside normalized values. Distinguish
   per-unit and total capacity, alternatives and thresholds. Normalize only
   supported formats; unfamiliar expressions become review findings.
3. Implement a verifier agent that judges support, missing qualifications and
   contradictory evidence using registered scoped tools. It returns structured
   findings with claim IDs, evidence IDs, severity and concise explanations.
   A valid quote location is not itself proof that a claim follows from the quote.
4. Cross-check output against the fact register/category coverage. Flag important
   omissions separately from unsupported claims and unread/unprocessed source.
   Distinguish verified, unsupported, conflicting, unresolved, and human-edited states.
5. Permit one evidence repair pass: give the writer only the findings and relevant
   evidence, preserve unaffected stable IDs, and revalidate changed claims. Shared
   budgets include retrieval/tool calls, schema repairs and verifier requests.
6. Produce a deterministic quality decision. Complete, supported output can become
   a draft ready for human review; partial input or unresolved critical verification
   failures cannot be approved for downstream use. Missing fields may remain
   explicitly unknown after complete review. No machine step auto-approves a summary.
7. Persist concise verification findings and metric definitions, not raw hidden
   reasoning. Do not turn reranker scores, self-ratings or the earlier 85% retrieval
   result into a percentage labelled summary confidence.

## Proposed implementation targets

- `backend/app/services/agents/nodes/verifier.py`, `verification.py`, and repair edges.
- Evidence/claim quality schemas and `test_summary_verification.py`.
- Graph-level budget and cycle-limit tests.

## Verification

Test fabricated pages/quotes/IDs, valid quotes supporting the wrong claim, wrong
EMD option/row, dropped conditions, crores versus rupees, MW versus per-unit MW,
conflicting dates, omissions, partial source coverage and unavailable evidence.
Inject a writer that repeatedly requests repair and prove the graph stops after
one allowed repair with a truthful final outcome.

Use annotated fixtures to assess semantics; two agents using the same model can
share mistakes. Treat live-model verification as another signal, not independent
proof or a replacement for Step 14's human-grounded benchmark.

## Exit criteria

- [ ] Invalid/out-of-scope citations cannot pass publication checks.
- [ ] Unsupported critical assertions are removed or explicitly quality-blocked.
- [ ] Repairs terminate within the shared call/token budget.
- [ ] Partial/stale/deleting source cannot receive downstream-ready approval.
- [ ] Review findings preserve meaning without fabricated confidence scores.
