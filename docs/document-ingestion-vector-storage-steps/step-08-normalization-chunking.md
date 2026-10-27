# Step 8: Normalize and Chunk Extracted Content

## Step Status

Repository implementation complete as of 2026-10-25. Release-worker verification is pending. The
approved immutable BGE tokenizer artifact/revision was not available in this environment, Docker
was unavailable, and the dependency vulnerability gate remains failed for pre-existing packages.
Document ingestion must remain disabled.

## Objective

Convert ordered extractor blocks into deterministic, model-sized chunks while preserving every
meaningful source reference needed for later summary and WBS evidence. The same source blocks and
configuration must always produce the same chunk sequence and hashes.

## Prerequisites

- Steps 6 and 7 produce valid `ExtractionResult` values.
- Packaged BGE tokenizer revision is approved.
- Target model sequence length is confirmed as 512 tokens.
- Chunk target is 400 tokens with 50-token overlap unless evidence approves a change.

## Normalization Rules

Normalize:

- CRLF/CR to LF;
- Unicode whitespace variants to meaningful standard spacing;
- repeated blank lines;
- unsafe control characters;
- parser-only artifacts documented by format fixtures;
- stable table/row separators.

Preserve:

- WBS and requirement identifiers;
- numbering, bullets, and heading hierarchy;
- dates, units, currency, quantities, percentages, and punctuation;
- table and spreadsheet column headers;
- exclusions, assumptions, constraints, risks, and negation;
- page, sheet, row, and block provenance.

Do not perform semantic rewriting, summarization, spell correction, translation, or LLM cleanup.

## Chunk Contract

Each chunk contains:

- deterministic ordinal;
- canonical content;
- model token count;
- SHA-256 of canonical content plus stable source identity where required;
- source block ordinal range;
- page number set/range;
- worksheet and row range when applicable;
- heading path;
- table-header context;
- extraction method metadata;
- truncation/split warning codes when applicable.

The chunk object does not yet contain an embedding. Step 9 attaches vectors, and Step 10 persists the
combined record.

## Chunking Algorithm

1. Normalize each block independently.
2. Remove blocks that are empty after normalization and record a count.
3. Tokenize with the exact packaged BGE tokenizer.
4. Group blocks inside the same logical section while remaining near the 400-token target.
5. Prefer boundaries in this order: section, page, paragraph, table region, row, sentence, token.
6. Split an oversized block deterministically using the same boundary order.
7. Apply approximately 50 tokens of overlap without duplicating an entire large table/section.
8. Repeat required table/worksheet header context in each dependent chunk.
9. Validate final token count is below the approved ceiling with formatting headroom.
10. Calculate ordinal, source range, and hash.

## Spreadsheet and Table Rules

- Keep the header with each chunk of dependent rows.
- Avoid mixing worksheets in one chunk.
- Avoid mixing unrelated table regions in one chunk.
- Keep a complete row when it fits.
- For an oversized row, split cells with column labels so meaning remains recoverable.
- Store exact row range separately from repeated header text.
- Do not flatten numeric cells in a way that loses column association.

## PDF and Word Rules

- Prefer heading-bound section chunks.
- Retain page references for all included blocks.
- A chunk may cross adjacent pages only when section continuity is clear and all pages are recorded.
- Preserve list hierarchy and numbered requirement sequences.
- Keep table rows associated with their header.

## Implementation Tasks

1. Add a model-tokenizer adapter loading from the packaged model directory.
2. Implement conservative text normalization as pure functions.
3. Implement source-aware block grouping.
4. Implement deterministic oversized-block splitting.
5. Implement overlap without losing provenance.
6. Implement table/worksheet header repetition.
7. Implement chunk validation and stable hashing.
8. Add coverage checks from retained blocks to chunks.
9. Add warnings and statistics for dropped empty blocks and forced splits.
10. Add property and regression tests for determinism and token limits.

## Files Expected to Change

- `backend/app/services/ingestion/normalization.py`
- `backend/app/services/ingestion/chunking.py`
- shared ingestion types
- tokenizer/model-loading helper used by worker readiness
- normalization and chunking tests

## Test Matrix

Normalization:

- mixed line endings and whitespace;
- control characters;
- Unicode text;
- requirement codes and numbered lists;
- currency, units, percentages, and dates;
- negative statements and scope exclusions;
- table delimiters and empty cells.

Chunking:

- block below target;
- multiple small paragraphs in one section;
- section transition near target;
- oversized paragraph;
- oversized table row;
- multi-page section;
- multi-sheet workbook;
- header repetition;
- exact target and maximum token boundaries;
- overlap and provenance;
- identical input produces identical chunks/hashes across runs;
- no retained source block disappears from coverage.

## Security Checklist

- [x] Tokenizer loads only packaged model artifacts.
- [x] No remote model/code loading occurs.
- [x] Content and metadata remain bounded.
- [x] Hashing does not replace authorization checks.
- [x] Canonical text is not written to logs.
- [x] Normalization does not interpret document instructions.
- [x] Chunk output contains no tenant/project identifiers and requires later scoped persistence.

## Verification

Run deterministic golden-fixture tests twice and compare serialized chunk content, metadata, token
counts, ordinals, and hashes. Review representative PDF, DOCX, XLSX, and CSV outputs to confirm scope
statements and numeric table meaning remain intact.

## Rollback

Chunker changes after data is active require a new chunker/extractor version and reprocessing. Never
mutate historical chunks in place while claiming the same processing version.

## Exit Criteria

- [x] Every retained block is covered by at least one chunk in repository tests.
- [x] No chunk exceeds the configured token ceiling in repository tests.
- [x] Identical inputs/configuration produce identical output and hashes in repository tests.
- [x] Tables and spreadsheet rows retain header/column meaning in synthetic fixtures.
- [x] Page, sheet, row, heading, and method provenance remain available.
- [x] Synthetic golden, boundary, and deterministic generated tests pass.

The checks above establish the repository contract. They do not constitute release verification
against the approved production BGE tokenizer artifact or worker image; see the Step 8 evidence.

## Handoff to Step 9

Provide a stable ordered chunk list containing canonical content, token count, hash, and provenance.
Step 9 embeds only canonical chunk content and attaches one 384-dimensional vector per chunk.

