"""Verify synchronized versions and the exported source manifest."""

import hashlib
import json
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "release-manifest.json").read_text())
python_version = tomllib.loads((root / "pyproject.toml").read_text())["project"][
    "version"
]
if {manifest["version"], python_version} != {python_version}:
    raise SystemExit("Python and manifest versions differ.")
for relative, expected in manifest["files"].items():
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"Hash mismatch: {relative}")
