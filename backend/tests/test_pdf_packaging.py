from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_pypdf_is_exactly_pinned() -> None:
    pyproject = (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"pypdf==6.21.2"' in pyproject


def test_api_and_ocr_worker_targets_are_separate_and_fail_closed() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    worker_start = dockerfile.index("FROM runtime-base AS ocr-worker")
    api_start = dockerfile.index("FROM runtime-base AS runtime", worker_start + 1)
    worker_stage = dockerfile[worker_start:api_start]
    api_stage = dockerfile[api_start:]

    assert '"ocrmypdf=$OCRMY_PDF_PACKAGE_VERSION"' in worker_stage
    assert '"tesseract-ocr=$TESSERACT_OCR_PACKAGE_VERSION"' in worker_stage
    assert '"tesseract-ocr-eng=$TESSERACT_ENG_PACKAGE_VERSION"' in worker_stage
    assert '"ghostscript=$GHOSTSCRIPT_PACKAGE_VERSION"' in worker_stage
    assert '"qpdf=$QPDF_PACKAGE_VERSION"' in worker_stage
    assert 'test -n "$OCRMY_PDF_PACKAGE_VERSION"' in worker_stage
    assert "USER wbs" in worker_stage
    assert "ocrmypdf" not in api_stage.lower()
    assert "tesseract" not in api_stage.lower()
    assert dockerfile.rstrip().endswith(
        'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]'
    )
