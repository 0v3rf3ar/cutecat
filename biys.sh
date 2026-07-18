#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_DIR=".venv-build"
OUT_DIR="dist"

pick_python() {
    if [ -n "${PYTHON_BIN:-}" ]; then echo "$PYTHON_BIN"; return; fi
    for c in python3.13 python3.12 python3.11 python3 python; do
        command -v "$c" >/dev/null 2>&1 && { echo "$c"; return; }
    done
    echo "error: no python interpreter found" >&2
    exit 1
}

PYTHON="$(pick_python)"
echo "==> Using $("$PYTHON" --version) ($(command -v "$PYTHON"))"

VOICE=1
[ "${CUTECAT_NO_VOICE:-}" = "1" ] && VOICE=0

rm -rf "$VENV_DIR"
"$PYTHON" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Installing build dependencies..."
python -m pip install --upgrade pip >/dev/null
if [ "$VOICE" = 1 ]; then
    pip install '.[discord,voice]' >/dev/null
else
    echo "==> Building without local voice (CUTECAT_NO_VOICE=1)."
    pip install '.[discord]' >/dev/null
fi
pip install --upgrade pyinstaller >/dev/null

echo "==> Checking the sources compile on $(python --version)..."
python -m compileall -q src/cutecat

COLLECT=(
    --collect-all cutecat
    --collect-all textual
    --collect-all discord
    --collect-all certifi
)
if [ "$VOICE" = 1 ]; then
    COLLECT+=(
        --collect-all faster_whisper
        --collect-all av
        --collect-all ctranslate2
        --collect-all onnxruntime
        --collect-all tokenizers
        --collect-all huggingface_hub
        --collect-all tqdm
        --collect-all yaml
    )
fi

echo "==> Bundling with PyInstaller (this takes a minute)..."
pyinstaller \
    --onefile \
    --noconfirm \
    --noupx \
    --name cutecat \
    --distpath "$OUT_DIR" \
    --workpath build \
    --specpath build \
    "${COLLECT[@]}" \
    entry.py

deactivate

echo
echo "==> Done. Binary at $OUT_DIR/cutecat"
echo "==> Quick check: printf '/help\\n/exit\\n' | $OUT_DIR/cutecat"
