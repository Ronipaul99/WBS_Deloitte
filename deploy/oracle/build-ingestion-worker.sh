#!/bin/bash
# Build and verify an ingestion image; do not replace running services.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backend_dir="$(cd -- "$script_dir/../../backend" && pwd)"
image="${1:-wbs-ingestion-worker:local}"

case "$(docker info --format '{{.Architecture}}')" in
    arm64|aarch64) ;;
    *) printf '%s\n' 'Run this helper against the Oracle ARM64 Docker host.' >&2; exit 1 ;;
esac

for source in Dockerfile worker-constraints.txt scripts/package_embedding_model.py \
    model-artifacts/bge-small-en-v1.5.manifest.json; do
    if [[ ! -f "$backend_dir/$source" ]]; then
        printf 'Missing build source: %s\n' "$backend_dir/$source" >&2
        exit 1
    fi
done

versions_file="$(mktemp)"
trap 'rm -f -- "$versions_file"' EXIT

printf '%s\n' 'Resolving exact OCR package versions in the worker base distribution...'
docker run --rm --platform linux/arm64 --entrypoint sh python:3.12-slim -ec '
    apt-get update >/dev/null
    for mapping in \
        ocrmypdf=OCRMY_PDF_PACKAGE_VERSION \
        tesseract-ocr=TESSERACT_OCR_PACKAGE_VERSION \
        tesseract-ocr-eng=TESSERACT_ENG_PACKAGE_VERSION \
        ghostscript=GHOSTSCRIPT_PACKAGE_VERSION \
        qpdf=QPDF_PACKAGE_VERSION; do
        package=${mapping%%=*}
        variable=${mapping#*=}
        version=$(apt-cache policy "$package" | awk "/Candidate:/ { print \$2; exit }")
        if [ -z "$version" ] || [ "$version" = "(none)" ]; then
            printf "No ARM64 package candidate for %s\n" "$package" >&2
            exit 1
        fi
        printf "%s=%s\n" "$variable" "$version"
    done
' > "$versions_file"

build_arguments=()
while IFS= read -r setting; do
    if [[ ! "$setting" =~ ^(OCRMY_PDF|TESSERACT_OCR|TESSERACT_ENG|GHOSTSCRIPT|QPDF)_PACKAGE_VERSION=.+$ ]]; then
        printf '%s\n' 'Unexpected package-version output; refusing to build.' >&2
        exit 1
    fi
    build_arguments+=(--build-arg "$setting")
done < "$versions_file"
[[ ${#build_arguments[@]} -eq 10 ]]
cp -- "$versions_file" "$script_dir/ocr-package-versions.env"
cat -- "$versions_file"

docker build --platform linux/arm64 --target ocr-worker \
    "${build_arguments[@]}" --tag "$image" "$backend_dir"

printf '\n%s\n' 'Verifying OCR tools and English language data with networking disabled...'
docker run --rm --network none --entrypoint sh "$image" -ec '
    printf "OCRMYPDF_EXPECTED_VERSION="
    ocrmypdf --version
    printf "TESSERACT_EXPECTED_VERSION="
    tesseract --version 2>&1 | head -n 1 | cut -d " " -f 2
    tesseract --list-langs 2>&1 | grep -qx eng
    gs --version
    qpdf --version
'

printf '\n%s\n' 'Verifying the packaged embedding model offline...'
docker run --rm --network none --entrypoint python "$image" -c '
from fastembed import TextEmbedding
model = TextEmbedding(
    model_name="BAAI/bge-small-en-v1.5",
    specific_model_path="/opt/wbs-models/bge-small-en-v1.5",
    local_files_only=True,
    providers=["CPUExecutionProvider"],
    threads=1,
)
vectors = list(model.embed(["ingestion worker installation check"], batch_size=1, parallel=None))
assert len(vectors) == 1 and len(vectors[0]) == 384
print("Offline embedding check passed: 384 dimensions")
'

docker run --rm --network none --entrypoint python "$image" -c '
import hashlib, json, subprocess
from pathlib import Path
root = Path("/opt/wbs-models/bge-small-en-v1.5")
manifest_bytes = (root / "model-manifest.json").read_bytes()
manifest = json.loads(manifest_bytes)
tokenizer = next(item for item in manifest["files"] if item["path"] == "tokenizer.json")
ocr = subprocess.check_output(["ocrmypdf", "--version"], text=True).splitlines()[0].strip()
tesseract = subprocess.check_output(["tesseract", "--version"], text=True).splitlines()[0].split()[1]
settings = {
    "OCR_ENABLED": "true",
    "OCR_LANGUAGES": "eng",
    "OCRMYPDF_EXPECTED_VERSION": ocr,
    "TESSERACT_EXPECTED_VERSION": tesseract,
    "DOCUMENT_PROCESSING_TEMP_ROOT": "/var/lib/wbs/processing",
    "EMBEDDING_PROVIDER": manifest["provider"],
    "EMBEDDING_MODEL": manifest["model_name"],
    "EMBEDDING_DIMENSIONS": str(manifest["dimensions"]),
    "EMBEDDING_MODEL_PATH": str(root),
    "EMBEDDING_MODEL_REVISION": manifest["model_revision"],
    "EMBEDDING_MODEL_MANIFEST_SHA256": hashlib.sha256(manifest_bytes).hexdigest(),
    "EMBEDDING_FORMATTING_VERSION": manifest["formatting_version"],
    "EMBEDDING_TOKENIZER_REVISION": manifest["model_revision"],
    "EMBEDDING_TOKENIZER_SHA256": tokenizer["sha256"],
    "EMBEDDING_MAX_CONCURRENT_BATCHES": "1",
    "EMBEDDING_CPU_THREADS": "1",
}
for key, value in settings.items():
    print(f"{key}={value}")
' > "$script_dir/worker-runtime.env"

printf '\nBuilt and verified image: %s\n' "$image"
printf 'Runtime version/model settings: %s/worker-runtime.env\n' "$script_dir"
printf '%s\n' 'Existing containers and ingestion enablement have not been changed.'
printf '%s\n' 'Configure the worker/API environment and Compose image before activating ingestion.'
