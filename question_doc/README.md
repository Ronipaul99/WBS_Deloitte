# Restore the shared RFP question bank

`question_bank.py` is the original `GENERAL_RFP_V1` template, Q001–Q007:
Project Overview, Project Scope, Key Deliverables, Assumptions, Constraints,
Exclusions, and Milestones & Timeline.

From the repository root, restore missing rows in the database configured by
`backend/.env`:

```powershell
.\backend\.venv\Scripts\python.exe question_doc\seed_question_bank.py --model-path backend\.data\question-bank-model\verified-bge
```

Use an existing checksum-verified worker model directory. The seeder uses the
worker's `FastEmbedProvider.embed_query`, pinned BGE model/revision, query prefix,
and 384-dimensional vectors. It reads the existing configuration without changing
`.env`, downloading models, or applying migrations. The table must already exist.
Writes use the separate direct migration role; the runtime role remains read-only.

The complete set is inserted and verified in one transaction. Repeating the seed
leaves matching entries unchanged. Conflicting content or embedding identity
aborts the transaction; a changed template requires a new question-set version.

To regenerate the vectors and compare every stored field without writing:

```powershell
.\backend\.venv\Scripts\python.exe question_doc\seed_question_bank.py --model-path backend\.data\question-bank-model\verified-bge --verify-only
```

Schema resets remove these shared reference rows as well as application data.
Run the seeder after any intentional reset that empties this table.
