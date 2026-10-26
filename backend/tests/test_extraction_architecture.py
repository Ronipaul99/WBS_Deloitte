import ast
from pathlib import Path

from app.services.ingestion.registry import get_release_extractor_registry
from app.services.ingestion.types import ConfirmedDocumentFormat

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_fastapi_routes_do_not_import_or_invoke_extractors() -> None:
    route_root = BACKEND_ROOT / "app" / "api" / "routes"
    for route_file in route_root.glob("*.py"):
        source = route_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not any("ingestion.extract" in module for module in imported_modules)
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "extract"
            for node in ast.walk(tree)
        )


def test_registry_uses_no_dynamic_loading_or_code_execution() -> None:
    registry_path = BACKEND_ROOT / "app" / "services" / "ingestion" / "registry.py"
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))
    banned_names = {"eval", "exec", "__import__"}

    assert not any(
        isinstance(node, ast.Import) and any(alias.name == "importlib" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "importlib" for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in banned_names
        for node in ast.walk(tree)
    )


def test_pdf_extractor_has_no_network_client_or_dynamic_code_loading() -> None:
    extractor_path = BACKEND_ROOT / "app" / "services" / "ingestion" / "extractors" / "pdf.py"
    tree = ast.parse(extractor_path.read_text(encoding="utf-8"))
    banned_modules = {"httpx", "importlib", "requests", "urllib", "socket"}
    banned_calls = {"eval", "exec", "__import__"}

    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name.split(".")[0] in banned_modules for alias in node.names)
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned_modules
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in banned_calls
        for node in ast.walk(tree)
    )


def test_release_registry_does_not_advertise_placeholder_extractors() -> None:
    registrations = get_release_extractor_registry().extractors
    assert tuple(extractor.format_name for extractor in registrations) == tuple(
        ConfirmedDocumentFormat
    )
    assert all(
        "fake" not in extractor.name and "stub" not in extractor.name for extractor in registrations
    )


def test_office_and_csv_extractors_have_no_network_shell_or_dynamic_loading() -> None:
    extractor_root = BACKEND_ROOT / "app" / "services" / "ingestion" / "extractors"
    banned_modules = {"httpx", "importlib", "requests", "socket", "subprocess", "urllib"}
    banned_calls = {"eval", "exec", "__import__"}
    for file_name in ("docx.py", "xlsx.py", "csv.py", "_common.py"):
        tree = ast.parse((extractor_root / file_name).read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.Import)
            and any(alias.name.split(".")[0] in banned_modules for alias in node.names)
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned_modules
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in banned_calls
            for node in ast.walk(tree)
        )


def test_api_readiness_does_not_import_office_or_csv_parser_modules() -> None:
    readiness_path = BACKEND_ROOT / "app" / "services" / "readiness.py"
    tree = ast.parse(readiness_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        module.endswith(("extractors.docx", "extractors.xlsx", "extractors.csv"))
        for module in imported_modules
    )


def test_routes_do_not_import_or_invoke_normalization_chunking_or_tokenizer() -> None:
    route_root = BACKEND_ROOT / "app" / "api" / "routes"
    forbidden = ("ingestion.normalization", "ingestion.chunking", "ingestion.tokenizer")
    for route_file in route_root.glob("*.py"):
        tree = ast.parse(route_file.read_text(encoding="utf-8"))
        imported_modules = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not any(any(name in module for name in forbidden) for module in imported_modules)


def test_tokenizer_adapter_has_no_network_remote_loading_or_dynamic_execution() -> None:
    tokenizer_path = BACKEND_ROOT / "app" / "services" / "ingestion" / "tokenizer.py"
    tree = ast.parse(tokenizer_path.read_text(encoding="utf-8"))
    banned_modules = {"httpx", "httpx2", "requests", "socket", "urllib"}
    banned_calls = {"eval", "exec", "__import__", "from_pretrained"}

    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name.split(".")[0] in banned_modules for alias in node.names)
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned_modules
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in banned_calls
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in banned_calls
        )
        for node in ast.walk(tree)
    )
