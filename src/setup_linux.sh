#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
python_bin="${S4_PYTHON:-python3}"
"$python_bin" -c 'import sys; assert sys.version_info[:2] == (3,12), "Use Python 3.12 (set S4_PYTHON if needed)"'
"$python_bin" -m venv .venv
.venv/bin/python -m pip install -r requirements-linux.txt
.venv/bin/python platform_setup.py "$@"
