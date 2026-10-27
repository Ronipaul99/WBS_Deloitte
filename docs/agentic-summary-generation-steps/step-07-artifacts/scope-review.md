# Step 7 scope review

Initial contents/hashes for 508 tracked and nonignored untracked files were
captured before implementation under ignored
`backend/.data/step07-initial-checkout.json`. The sanitized
[manifest](scope-manifest.json) identifies files changed since that snapshot.
Pre-existing staged/dirty work was preserved; no staging/commit/push occurred.

Allowed earlier-step changes are limited to:

1. Evidence artifact types and the bounded evidence-tool allowance in Step 5's
   typed execution/NodeResult contracts, retaining existing transitions/recovery.
2. Allowlisted immutable evidence step-record validation in the existing ORM.
3. A type-checking-only repository import in retrieval so helper reuse does not
   initialize configured sessions. Existing active retrieval behavior is unchanged.
4. Additive migration `e53c7a19b402`, based on initial head `c29f4b8e710a`, justified
   in [persistence gap](persistence-gap.md). No old migration or source constraint
   was rewritten or loosened.
5. Expected application-head constants in schema/storage tests. The question-bank
   test has only that head expectation change; question-bank implementation,
   source files, seeding, data and embeddings were preserved.

No routes, UI, summary agents/prompts, graph handler registration, summary endpoint
rewiring, review/approval flow, WBS behavior or generic recovery redesign was added.
No `.env`, actual credentials, secrets, dependency manifests, Docker/Nginx runtime
configuration, CI or live VM was edited. No real generation-provider call,
model download, application-database query or cloud-document fetch was performed.

Verification uses isolated synthetic SQLite databases, skipped opt-in disposable
PostgreSQL tests and read-only local historical RFP artifacts. Extracted customer
text, source hashes/identifiers, vectors and full audit outputs remain outside
committed evidence under ignored local data. No private RFP fixture was committed.
