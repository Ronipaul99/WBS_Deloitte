"""Offline native-PDF, tokenizer, embedding, and installed-tool checks."""

import json
from pathlib import Path
import shutil
from uuid import uuid4

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.config import get_settings
from app.services.ingestion.chunk_types import ChunkingPolicy
from app.services.ingestion.chunking import DocumentChunker
from app.services.ingestion.embeddings.base import EmbeddingPolicy, embed_canonical_chunks
from app.services.ingestion.embeddings.fastembed_provider import get_process_embedding_provider
from app.services.ingestion.extractors.pdf import PdfExtractor
from app.services.ingestion.tokenizer import LocalBgeTokenizer
from app.services.ingestion.types import ExtractionLimits
from app.services.readiness import (
    embedding_model_path_is_ready,
    embedding_runtime_is_ready,
    extractor_registry_is_ready,
    ocr_runtime_is_ready,
    tokenizer_runtime_is_ready,
)


def main() -> None:
    settings = get_settings()
    checks = [
        ("model_files", lambda: embedding_model_path_is_ready(settings)),
        ("tokenizer", lambda: tokenizer_runtime_is_ready(settings)),
        ("embeddings", lambda: embedding_runtime_is_ready(settings)),
        ("ocr_versions_and_language", lambda: ocr_runtime_is_ready(settings)),
        ("extractors", lambda: extractor_registry_is_ready(settings=settings)),
    ]
    for name, check in checks:
        check()
        print(json.dumps({name: "passed"}), flush=True)

    root = Path(settings.document_processing_temp_root)
    workspace = root / str(uuid4())
    workspace.mkdir(mode=0o700)
    try:
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
        })
        stream = DecodedStreamObject()
        stream.set_data(
            b"BT /F1 16 Tf 50 740 Td (PROJECT DELIVERY PLAN) Tj "
            b"0 -30 Td (Scope estimation and project milestones.) Tj "
            b"0 -30 Td (Acceptance criteria and delivery responsibilities.) Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        source = workspace / "input.pdf"
        with source.open("wb") as output:
            writer.write(output)
        source.chmod(0o600)
        result = PdfExtractor.from_settings(settings).extract(
            source, ExtractionLimits.from_settings(settings)
        )
        extracted = " ".join(block.text for block in result.blocks).upper()
        assert "PROJECT" in extracted and "DELIVERY" in extracted
        print(json.dumps({"native_pdf_extraction": "passed", "blocks": len(result.blocks)}), flush=True)
        chunker = DocumentChunker(
            tokenizer=LocalBgeTokenizer.from_settings(settings),
            policy=ChunkingPolicy.from_settings(settings),
        )
        chunking = chunker.chunk(result)
        embedded = embed_canonical_chunks(
            chunking.chunks,
            provider=get_process_embedding_provider(settings),
            policy=EmbeddingPolicy.from_settings(settings),
        )
        assert embedded.items and embedded.metadata.dimensions == 384
        print(json.dumps({"native_pdf_to_embeddings": "passed", "chunks": len(embedded.items)}), flush=True)
    finally:
        shutil.rmtree(workspace)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"verification_error_type": type(error).__name__, "code": getattr(error, "code", None)}), flush=True)
        raise SystemExit(1) from None
