# Shared RFP summary questions

`question_bank.py` defines `GENERAL_RFP_V1`, with Q001–Q007:

| ID | Category |
| --- | --- |
| Q001 | Project Overview |
| Q002 | Project Scope |
| Q003 | Key Deliverables |
| Q004 | Assumptions |
| Q005 | Constraints |
| Q006 | Exclusions |
| Q007 | Milestones & Timeline |

The question text, extraction instructions, answer type, display order, content
digest, and query vector are stored in `public.rfp_question_bank`. This shared
system template contains no tenant or document content. The application runtime
role has SELECT access; seeding uses the separate direct migration role.

Embeddings use the **same provider and pinned artifact as the chunk worker**:
FastEmbed, `BAAI/bge-small-en-v1.5`, revision
`aa8f8b060edb00e03bfdd08813a2949946c8ba55`, 384 dimensions, manifest SHA-256
`609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0`.
Question text goes through `FastEmbedProvider.embed_query`, which adds
`Represent this sentence for searching relevant passages: ` exactly once.
Document chunks retain their existing document formatting. Extraction instructions
are stored separately and are not included in the question embedding.

## Migrate and seed

From the repository root, using the configured `backend/.env` credentials:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade a13d9e7b602c
Set-Location ..
.\backend\.venv\Scripts\python.exe question_doc\seed_question_bank.py --model-path backend\.data\question-bank-model\verified-bge
```

The example model path is the local operator copy of the verified worker artifact.
On the worker, omit `--model-path` to use `EMBEDDING_MODEL_PATH`. The worker extra
dependencies must be installed. The script does not download or substitute models,
modify `.env`, or initialize unrelated application tables.

The question-table revision branches from `e71c4a9b203d` so it can be deployed
without applying pending agent migrations. `c29f4b8e710a` merges that branch with
the existing agent migration chain for a single application head. Use the exact
question revision above for this limited deployment; `upgrade head` also applies
the remaining agent migrations.

All seven rows are committed in one transaction. Repeating the seed reports seven
unchanged rows. Changed question content, instructions or embedding identity is
rejected for an existing version; create a new question-set ID for those changes.
No vector search index is needed for seven templates, which are loaded by ID.

```powershell
.\backend\.venv\Scripts\python.exe question_doc\seed_question_bank.py --model-path backend\.data\question-bank-model\verified-bge --verify-only
```

`--verify-only` regenerates the embeddings locally and compares every stored field
and vector without writing rows. A simple database inspection is:

```sql
SELECT question_id, category, question_text, embedding_model,
       embedding_model_revision, vector_dims(embedding) AS dimensions
FROM public.rfp_question_bank
WHERE question_set_id = 'GENERAL_RFP_V1'
ORDER BY ordinal;
```

## Using the bank during summary generation

`app.services.agents.question_bank.load_question_set(session, 'GENERAL_RFP_V1')`
loads the ordered template and cached query embeddings. Before searching document
chunks, match the saved embedding identity to the pinned document run and enforce
tenant/project/document/run scope. Keep the complete reading-batch coverage planned
in Steps 7–8; these seven searches supplement that coverage.

This change prepares and seeds the question bank. Wiring the summary analyst and
pinned-run retrieval to consume it is part of the subsequent summary workflow work.
