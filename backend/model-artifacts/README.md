# Embedding Release Inventory

This directory contains metadata only. It must never contain ONNX weights, tokenizer binaries, or
another model payload.

## Model artifact

- Application model name: `BAAI/bge-small-en-v1.5`
- FastEmbed artifact repository: `Qdrant/bge-small-en-v1.5-onnx-Q`
- Artifact revision: `aa8f8b060edb00e03bfdd08813a2949946c8ba55`
- Original BAAI model revision recorded for provenance:
  `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`
- Dimensions: `384`
- Formatting policy: `bge-small-en-v1.5-format-v1`
- Manifest SHA-256:
  `609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0`
- Model license: MIT, copied during the build from immutable FlagEmbedding commit
  `fd1a2bdf69488ffebe0327999d4400d8c8058a0b`

The JSON manifest records every expected runtime filename, exact byte size, SHA-256, and immutable
download URL. The model-builder refuses traversal, non-HTTPS initial sources, unapproved hosts,
oversized artifacts, size mismatches, or digest mismatches. `model-manifest.json` is copied into the
runtime directory so worker readiness can repeat the validation before loading ONNX.

## Worker dependency pins

The `worker` optional dependency group pins the primary runtime graph below. The complete resolved
closure is pinned in `backend/worker-constraints.txt`, and both worker wheel creation and worker
installation enforce that constraints file. The API target does not install this worker graph.

| Package | Version | Installed metadata license |
| --- | --- | --- |
| fastembed | 0.9.0 | Apache-2.0 |
| onnxruntime | 1.31.0 | MIT |
| numpy | 2.5.4 | BSD-3-Clause and bundled notices |
| tokenizers | 0.22.2 | Metadata incomplete; approval required |
| huggingface-hub | 1.33.0 | Apache-2.0 |
| loguru | 0.7.3 | Metadata incomplete; approval required |
| mmh3 | 5.3.1 | MIT |
| pillow | 12.3.0 | MIT-CMU |
| protobuf | 7.36.2 | BSD-3-Clause |
| py-rust-stemmers | 0.1.8 | Metadata incomplete; approval required |
| requests | 2.34.2 | Apache-2.0 |
| tqdm | 4.70.1 | MPL-2.0 and MIT |
| flatbuffers | 25.12.19 | Apache-2.0 |

FastEmbed `0.9.0` is the repository-pinned release candidate. Its PyPI wheel SHA-256 is
`273d408edec8c0f161711d8f6e44e4a5b559d18e8edf6bf805415d55dc772846`; PyPI reports no provenance
attestation for that wheel. Security and license approval therefore remain release gates.

## Current release blockers

As of 2026-10-26, the dependency audit reports vulnerabilities in Pillow `12.3.0` with fixes in
`13.0.0`, while FastEmbed `0.9.0` declares `pillow<13`. The audit also retains pre-existing findings
in certifi, cryptography, pip, and development-only pytest. The worker must not be release-approved
until these findings are resolved or formally dispositioned and incomplete package-license metadata
is reviewed.

Primary public sources:

- https://pypi.org/project/fastembed/0.9.0/
- https://github.com/qdrant/fastembed/tree/v0.9.0
- https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q/tree/aa8f8b060edb00e03bfdd08813a2949946c8ba55
- https://huggingface.co/BAAI/bge-small-en-v1.5/tree/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a
- https://github.com/FlagOpen/FlagEmbedding/blob/fd1a2bdf69488ffebe0327999d4400d8c8058a0b/LICENSE
