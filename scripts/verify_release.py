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
npm_version = json.loads((root / "launcher/package.json").read_text())["version"]
root_package = root / "package.json"
root_npm_version = (
    json.loads(root_package.read_text())["version"]
    if root_package.is_file()
    else npm_version
)
if len({manifest["version"], python_version, npm_version, root_npm_version}) != 1:
    raise SystemExit("Python, npm and manifest versions differ.")
for relative, expected in manifest["files"].items():
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"Hash mismatch: {relative}")
