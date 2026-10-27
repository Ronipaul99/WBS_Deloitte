from pathlib import Path

import pytest
from pdf_extraction_fixtures import pdf_policy
from pdf_fixtures import scanned_pdf_bytes, text_pdf_bytes

from app.services.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.services.ingestion.extractors import pdf


class CompletedProcess:
    pid = 4321
    returncode = 0

    def poll(self) -> int:
        return 0

    def wait(self, timeout: int | None = None) -> int:
        del timeout
        return 0


def test_ocr_process_uses_fixed_argument_list_shell_false_and_safe_environment(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    input_path.write_bytes(scanned_pdf_bytes())
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        Path(command[-1]).write_bytes(text_pdf_bytes())
        return CompletedProcess()

    monkeypatch.setattr(pdf.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(pdf, "_apply_process_limits", lambda *_args: True)
    monkeypatch.setattr(pdf.SubprocessOcrRunner, "is_ready", lambda *_args: True)

    pdf.SubprocessOcrRunner().run(input_path, output_path, (1,), pdf_policy())

    assert captured["shell"] is False
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["command"] == (
        "ocrmypdf",
        "--force-ocr",
        "--output-type",
        "pdf",
        "--optimize",
        "0",
        "--jobs",
        "1",
        "--tesseract-timeout",
        "30",
        "--language",
        "eng",
        "--pages",
        "1",
        "--",
        str(input_path),
        str(output_path),
    )
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert set(environment) == {"HOME", "LANG", "LC_ALL", "OMP_THREAD_LIMIT", "PATH", "TMPDIR"}
    assert input_path.read_bytes() == scanned_pdf_bytes()
    assert not list(tmp_path.glob("ocr-*.log"))


def test_missing_executable_and_timeout_map_to_stable_errors(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(scanned_pdf_bytes())

    monkeypatch.setattr(
        pdf.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("private path")),
    )
    with pytest.raises(ExtractionError) as unavailable:
        pdf.SubprocessOcrRunner().run(
            input_path,
            tmp_path / "missing.pdf",
            (1,),
            pdf_policy(),
        )
    assert unavailable.value.code is ExtractionErrorCode.OCR_UNAVAILABLE

    class RunningProcess(CompletedProcess):
        returncode = None

        def poll(self):
            return None

    process = RunningProcess()
    monkeypatch.setattr(pdf.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(pdf, "_apply_process_limits", lambda *_args: True)
    monkeypatch.setattr(pdf.SubprocessOcrRunner, "is_ready", lambda *_args: True)
    terminated: list[object] = []
    monkeypatch.setattr(pdf, "_terminate_process", terminated.append)
    with pytest.raises(ExtractionError) as timeout:
        pdf.SubprocessOcrRunner().run(
            input_path,
            tmp_path / "timeout.pdf",
            (1,),
            pdf_policy(ocr_timeout_seconds=-1),
        )
    assert timeout.value.code is ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT
    assert terminated == [process]
    assert not list(tmp_path.glob("ocr-*.log"))


def test_nonzero_ocr_exit_maps_to_ocr_failed(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(scanned_pdf_bytes())

    class FailedProcess(CompletedProcess):
        returncode = 2

    monkeypatch.setattr(pdf.subprocess, "Popen", lambda *_args, **_kwargs: FailedProcess())
    monkeypatch.setattr(pdf, "_apply_process_limits", lambda *_args: True)
    monkeypatch.setattr(pdf.SubprocessOcrRunner, "is_ready", lambda *_args: True)

    with pytest.raises(ExtractionError) as error:
        pdf.SubprocessOcrRunner().run(
            input_path,
            tmp_path / "output.pdf",
            (1,),
            pdf_policy(),
        )
    assert error.value.code is ExtractionErrorCode.OCR_FAILED


def test_bounded_process_output_fails_as_resource_exhaustion(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    input_path.write_bytes(scanned_pdf_bytes())

    def noisy_popen(command, **kwargs):
        kwargs["stdout"].write(b"x" * 2048)
        kwargs["stdout"].flush()
        Path(command[-1]).write_bytes(text_pdf_bytes())
        return CompletedProcess()

    monkeypatch.setattr(pdf.subprocess, "Popen", noisy_popen)
    monkeypatch.setattr(pdf, "_apply_process_limits", lambda *_args: True)
    monkeypatch.setattr(pdf.SubprocessOcrRunner, "is_ready", lambda *_args: True)

    with pytest.raises(ExtractionError) as error:
        pdf.SubprocessOcrRunner().run(
            input_path,
            output_path,
            (1,),
            pdf_policy(ocr_process_output_maximum_bytes=1024),
        )
    assert error.value.code is ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED
    assert not list(tmp_path.glob("ocr-*.log"))


def test_temporary_disk_limit_is_recursive(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    input_path.write_bytes(scanned_pdf_bytes())

    def disk_filling_popen(command, **_kwargs):
        nested = tmp_path / "ocr-intermediate"
        nested.mkdir()
        (nested / "bounded.tmp").write_bytes(b"x" * 2048)
        Path(command[-1]).write_bytes(text_pdf_bytes())
        return CompletedProcess()

    monkeypatch.setattr(pdf.subprocess, "Popen", disk_filling_popen)
    monkeypatch.setattr(pdf, "_apply_process_limits", lambda *_args: True)
    monkeypatch.setattr(pdf.SubprocessOcrRunner, "is_ready", lambda *_args: True)

    with pytest.raises(ExtractionError) as error:
        pdf.SubprocessOcrRunner().run(
            input_path,
            output_path,
            (1,),
            pdf_policy(ocr_maximum_temporary_bytes=1024),
        )
    assert error.value.code is ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED
    assert not (tmp_path / "ocr-intermediate").exists()


def test_interruption_terminates_child_and_removes_process_logs(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(scanned_pdf_bytes())

    class RunningProcess(CompletedProcess):
        returncode = None

        def poll(self):
            return None

    process = RunningProcess()
    terminated: list[object] = []
    monkeypatch.setattr(pdf.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(pdf, "_apply_process_limits", lambda *_args: True)
    monkeypatch.setattr(pdf.SubprocessOcrRunner, "is_ready", lambda *_args: True)
    monkeypatch.setattr(pdf, "_terminate_process", terminated.append)
    monkeypatch.setattr(
        pdf.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    with pytest.raises(KeyboardInterrupt):
        pdf.SubprocessOcrRunner().run(
            input_path,
            tmp_path / "output.pdf",
            (1,),
            pdf_policy(),
        )
    assert terminated == [process]
    assert not list(tmp_path.glob("ocr-*.log"))


def test_output_cannot_overwrite_input_or_escape_workspace(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(scanned_pdf_bytes())
    runner = pdf.SubprocessOcrRunner()

    for unsafe_output in (input_path, tmp_path.parent / "escaped.pdf"):
        with pytest.raises(ExtractionError) as error:
            runner.run(input_path, unsafe_output, (1,), pdf_policy())
        assert error.value.code is ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED


def test_runtime_readiness_requires_exact_versions_and_language(monkeypatch) -> None:
    outputs = {
        ("ocrmypdf", "--version"): "test-ocrmypdf\n",
        ("tesseract", "--version"): "tesseract test-tesseract\n",
        ("tesseract", "--list-langs"): "List of available languages (1):\neng\n",
    }
    monkeypatch.setattr(
        pdf,
        "_read_bounded_command_output",
        lambda command, **_kwargs: outputs.get(command),
    )
    runner = pdf.SubprocessOcrRunner()

    assert runner.is_ready(pdf_policy()) is True
    assert runner.is_ready(pdf_policy(ocrmypdf_expected_version="different")) is False
    assert runner.is_ready(pdf_policy(ocr_languages=("missing",))) is False
    assert runner.is_ready(pdf_policy(ocrmypdf_expected_version=None)) is False
