#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${S4_PYTHON:-$root/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then python_bin="${S4_PYTHON:-python3}"; fi
exec "$python_bin" "$root/qt_app.py" "$@"
