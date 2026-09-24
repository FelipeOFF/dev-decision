"""Verify the public release manifest and the wheel hashes recorded after the build."""

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

_PRIVATE_NAMES = frozenset(
    {"package.json", "app.py", "credentials", "credentials.json", ".env"}
)
_PRIVATE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".log", ".key")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(root: Path) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text())
    version = project["project"]["version"]
    if not isinstance(version, str) or not version:
        raise SystemExit("The Python release version is missing.")
    return version


def _load(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "release-manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise SystemExit("The release manifest is invalid.")
    return manifest


def _save(root: Path, manifest: dict[str, object]) -> None:
    (root / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def _private_wheel_path(name: str) -> bool:
    parts = name.casefold().split("/")
    return (
        parts[-1] in _PRIVATE_NAMES
        or "credentials" in parts
        or parts[-1].endswith(_PRIVATE_SUFFIXES)
    )


def _check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if any(_private_wheel_path(name) for name in archive.namelist()):
            raise SystemExit("The wheel contains a private release path.")


def _verify_sources(root: Path, manifest: dict[str, object], version: str) -> None:
    if manifest.get("version") != version:
        raise SystemExit("Python and manifest versions differ.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit("The manifest has no source files.")
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise SystemExit("The manifest source hashes are invalid.")
        if _sha256(root / relative) != expected:
            raise SystemExit(f"Hash mismatch: {relative}")


def _wheel_paths(root: Path) -> list[Path]:
    dist = root / "dist"
    if not dist.is_dir():
        return []
    return sorted(path for path in dist.glob("*.whl") if path.is_file())


def _prefix(version: str) -> str:
    return f"specgate_client-{version}-"


def _stamp(root: Path, manifest: dict[str, object], version: str) -> dict[str, object]:
    wheels = _wheel_paths(root)
    if len(wheels) != 1:
        raise SystemExit("The release needs exactly one wheel.")
    wheel = wheels[0]
    if not wheel.name.startswith(_prefix(version)):
        raise SystemExit("The wheel name does not match the manifest version.")
    _check_wheel(wheel)
    updated = dict(manifest)
    updated["version"] = version
    updated["wheels"] = {wheel.name: _sha256(wheel)}
    return updated


def _verify_wheels(root: Path, manifest: dict[str, object], version: str) -> None:
    wheels = _wheel_paths(root)
    recorded = manifest.get("wheels")
    if not wheels and recorded is None:
        return
    if not isinstance(recorded, dict) or not recorded:
        raise SystemExit("The manifest is missing wheel hashes.")
    if {path.name for path in wheels} != set(recorded):
        raise SystemExit("The manifest wheel hashes do not match dist.")
    for path in wheels:
        digest = recorded.get(path.name)
        if (
            not path.name.startswith(_prefix(version))
            or not isinstance(digest, str)
            or digest != _sha256(path)
        ):
            raise SystemExit(f"Hash mismatch: {path.name}")
        _check_wheel(path)


def main(argv: list[str] | None = None, *, root: Path | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stamp-wheels", action="store_true")
    args = parser.parse_args(argv)
    base = root or Path(__file__).resolve().parents[1]
    version = _version(base)
    manifest = _load(base)
    _verify_sources(base, manifest, version)
    if args.stamp_wheels:
        manifest = _stamp(base, manifest, version)
        _save(base, manifest)
    _verify_wheels(base, manifest, version)


if __name__ == "__main__":
    main()
