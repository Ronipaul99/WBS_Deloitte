# Question bank implementation and Neon verification

Verified on 2026-10-27 against the database configured in `backend/.env`.
Credentials and connection URLs are intentionally omitted.

## Source analysis

The three source files are in the workspace's `question_doc/` directory. The
Downloads paths supplied in the request were no longer present.

- `question_bank.py` contains seven questions, Q001–Q007 in `GENERAL_RFP_V1`.
  Their text, instructions and answer types were preserved; formatting was cleaned up.
- The original embedding helper used SentenceTransformers and imports absent from
  this backend. It now delegates to the same verified FastEmbed provider as the worker.
- The original seed referenced nonexistent schema/connect helpers and overwrote
  records on `question_id` alone. The replacement uses the existing direct migration
  connection, explicit migrations, a `(question_set_id, question_id)` primary key,
  atomic inserts, complete read-back validation and safe repeated execution.

## Applied database change

Neon was at `e71c4a9b203d`. Only question-bank revision `a13d9e7b602c` was applied.
Pending agent revisions were not deployed. The repository merge revision
`c29f4b8e710a` leaves a single eventual application head.

Created `public.rfp_question_bank`; seeded seven rows under `GENERAL_RFP_V1`.
The table retains question text, instructions, answer type, order, content SHA-256,
query vector and the model/provider/revision/manifest/formatting identity.

| Question | Category | Dimensions |
| --- | --- | --- |
| Q001 | Project Overview | 384 |
| Q002 | Project Scope | 384 |
| Q003 | Key Deliverables | 384 |
| Q004 | Assumptions | 384 |
| Q005 | Constraints | 384 |
| Q006 | Exclusions | 384 |
| Q007 | Milestones & Timeline | 384 |

Confirmed completed document runs use the same embedding identity:

- Provider: `fastembed`
- Model: `BAAI/bge-small-en-v1.5`
- Model revision: `aa8f8b060edb00e03bfdd08813a2949946c8ba55`
- Dimensions: `384`
- Formatting: `bge-small-en-v1.5-format-v1`
- Manifest: `609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0`

The exact artifact was downloaded using the existing checksum-verifying model
packager into ignored local data. A local LF-normalized copy of the metadata
manifest matches the configured digest; the checked-out CRLF file does not.
No tracked manifest or environment settings were changed. All seven vectors
have unit norm and use the worker's query prefix exactly once.

## Verification

- Seed output: `inserted=7`, `unchanged=0`.
- `--verify-only`: `verified=7`; compared all question fields, embedding identity
  and every vector component after regenerating with the actual worker model.
- The runtime connection successfully loaded all seven rows in ordinal order.
- Runtime table privileges: SELECT true; INSERT, UPDATE, DELETE and TRUNCATE false.
- Question-bank tests: nine passing cases, including template-version isolation,
  safe reruns, atomic rollback, query/model validation and independent migration path.
- Ruff checks passed for the new implementation, migration, tests and question files.
- Broader migration/storage regression run: 78 passed, one failed. The failure is
  the existing SQLite autogeneration mismatch for `fk_profile_qualification_test`.
  It was reproduced at the previous `d42a91c7e806` migration without the question
  table; unrelated LLM schema code was left unchanged.

The table and read helper are ready. The future evidence analyst/pinned-run
retrieval workflow still needs to consume these cached question vectors and
preserve the full-document coverage required by Steps 7–8.
