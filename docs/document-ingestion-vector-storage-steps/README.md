# Document Ingestion and Vector Storage Steps

## Purpose

This directory converts the master
`docs/document-ingestion-vector-storage-execution-plan.md` into independently executable development
steps. Complete the steps in order because each document defines the contract required by the next.

The scope ends when an uploaded project document has an active, tenant- and project-isolated set of
source-linked embeddings in Neon pgvector. Summary generation and WBS generation are not included.

## Global Decisions

- Use one release-grade runtime path in every deployed environment.
- Use Neon S3-compatible object storage for original documents.
- Use Neon PostgreSQL and pgvector for extracted chunks and vectors.
- Use Celery and Redis for all ingestion execution.
- Use FastEmbed with `BAAI/bge-small-en-v1.5` and `VECTOR(384)`.
- Package the model in the worker image; never download it during a document request.
- Support PDF, DOCX, XLSX, and CSV.
- Support scanned PDFs through OCRmyPDF and Tesseract.
- Do not advertise `.doc` or `.xls` unless an approved converter is implemented.
- Enforce tenant and project scope in authorization, SQL predicates, constraints, and RLS.
- Automated tests may use test doubles, but no alternate deployed local runtime is permitted.

## Execution Order

| Step | Document | Depends on | Primary deliverable |
| --- | --- | --- | --- |
| 1 | [Release configuration gate](step-01-release-configuration-gate.md) | Existing backend | Fail-closed release settings |
| 2 | [PDF upload support](step-02-pdf-upload-support.md) | Step 1 | Verified real PDF upload |
| 3 | [pgvector ingestion schema](step-03-pgvector-ingestion-schema.md) | Step 1 | Vector and processing-run schema |
| 4 | [Object download and malware scan](step-04-object-download-malware-scan.md) | Steps 1-2 | Trusted temporary input |
| 5 | [Extraction contract](step-05-extraction-contract.md) | Steps 3-4 | Common extractor interface |
| 6 | [PDF extraction and OCR](step-06-pdf-extraction-ocr.md) | Step 5 | Page-linked PDF blocks |
| 7 | [DOCX, XLSX, and CSV extraction](step-07-office-csv-extraction.md) | Step 5 | Source-linked Office/CSV blocks |
| 8 | [Normalization and chunking](step-08-normalization-chunking.md) | Steps 6-7 | Stable model-sized chunks |
| 9 | [FastEmbed integration](step-09-fastembed-integration.md) | Steps 1 and 8 | Packaged embedding runtime |
| 10 | [Transactional vector persistence](step-10-vector-persistence.md) | Steps 3 and 9 | Atomic active vector run |
| 11 | [Ingestion orchestration and APIs](step-11-ingestion-orchestration-apis.md) | Steps 4-10 | Durable asynchronous workflow |
| 12 | [React workflow integration](step-12-react-workflow-integration.md) | Step 11 | End-user processing experience |
| 13 | [Deletion, retention, and reconciliation](step-13-deletion-retention-reconciliation.md) | Steps 10-12 | Complete lifecycle controls |

## Completion Rules

For each step:

1. satisfy every prerequisite;
2. implement only the documented scope;
3. add the specified tests;
4. run the applicable verification commands;
5. complete the security checklist;
6. record implementation evidence;
7. satisfy all exit criteria before starting a dependent step.

Do not mark a step complete because code exists. Completion requires test evidence and all listed
release gates that are controllable from the repository. External platform gates remain explicitly
pending until verified in the target environment.

## Suggested Evidence Layout

Create an evidence folder only when implementation begins:

```text
docs/document-ingestion-vector-storage-steps/step-NN-artifacts/
  implementation-evidence.md
  test-results.md
  residual-risks.md
```

Evidence must not contain secrets, document contents, raw embeddings, private object URLs, or
customer identifiers.

