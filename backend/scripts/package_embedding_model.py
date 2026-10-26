from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

_MAX_MANIFEST_BYTES = 128 * 1024
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_ALLOWED_HOSTS = frozenset({"huggingface.co", "raw.githubusercontent.com"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("manifest file path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {"", ".", ".."}:
        raise ValueError("manifest file path is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("manifest file path is invalid")
    return value


def _download(url: str, destination: Path, maximum_bytes: int) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "wbs-model-builder/1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("xb") as output:
        final_host = urllib.parse.urlparse(response.geturl()).hostname
        if not final_host or (
            final_host not in _ALLOWED_HOSTS
            and not final_host.endswith(".huggingface.co")
            and not final_host.endswith(".hf.co")
        ):
            raise ValueError("model artifact redirect host is not allowed")
        total = 0
        while True:
            chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise ValueError("model artifact exceeds its declared size")
            output.write(chunk)


def package_model(
    manifest_path: Path,
    destination: Path,
    expected_manifest_sha256: str,
) -> None:
    if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("model manifest exceeds the safety limit")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError("model manifest integrity validation failed")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("model manifest has no files")

    destination.mkdir(parents=True, exist_ok=False)
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("model manifest file entry is invalid")
        name = _safe_file_name(entry.get("path"))
        size = entry.get("size")
        expected_sha256 = entry.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError("model manifest file integrity data is invalid")

        target = destination / name
        generated = entry.get("generated_content")
        source_url = entry.get("source_url")
        if isinstance(generated, str) and source_url is None:
            target.write_text(generated, encoding="ascii", newline="\n")
        elif isinstance(source_url, str) and generated is None:
            source = urllib.parse.urlparse(source_url)
            if source.scheme != "https" or source.hostname not in _ALLOWED_HOSTS:
                raise ValueError("model artifact source host is not allowed")
            with tempfile.TemporaryDirectory(dir=destination) as temporary:
                partial = Path(temporary) / "artifact"
                _download(source_url, partial, size)
                os.replace(partial, target)
        else:
            raise ValueError("model manifest file source is invalid")

        if target.stat().st_size != size or _sha256(target) != expected_sha256:
            target.unlink(missing_ok=True)
            raise ValueError("model artifact integrity validation failed")

    manifest_destination = destination / "model-manifest.json"
    manifest_destination.write_bytes(manifest_path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    package_model(
        arguments.manifest,
        arguments.destination,
        arguments.manifest_sha256,
    )


if __name__ == "__main__":
    main()
