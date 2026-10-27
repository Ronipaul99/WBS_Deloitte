from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_office_and_csv_dependencies_are_exactly_pinned() -> None:
    pyproject = (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"python-docx==1.2.0"' in pyproject
    assert '"openpyxl==3.1.5"' in pyproject
    assert '"defusedxml==0.7.1"' in pyproject
    assert "pandas" not in pyproject.casefold()
    assert "libreoffice" not in pyproject.casefold()
