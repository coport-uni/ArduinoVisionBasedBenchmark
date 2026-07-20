"""Shared helpers: timestamps, atomic JSON writes, secret redaction."""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

# Environment variable names whose values must never be logged (NFR3).
SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")


def now_iso() -> str:
    """Return the current local time as an ISO 8601 string (NFR2)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json_atomic(path: Path, data: object) -> None:
    """Write JSON to *path* atomically via a temp file and os.replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def append_line(path: Path, line: str) -> None:
    """Append one line to *path* (append-only logs, NFR2)."""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")


def redact_env_keys(env: dict[str, str]) -> list[str]:
    """Return env var *names* only, for logging without values (NFR3)."""
    return sorted(env.keys())


def is_secret_env(name: str) -> bool:
    """Return True when an env var name looks like a credential."""
    upper = name.upper()
    return any(marker in upper for marker in SECRET_ENV_MARKERS)


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(trial_dir: Path) -> None:
    """Write manifest.json with a SHA-256 per artifact (NFR2 integrity)."""
    entries = {}
    for item in sorted(trial_dir.rglob("*")):
        if item.is_file() and item.name != "manifest.json":
            entries[str(item.relative_to(trial_dir))] = sha256_file(item)
    write_json_atomic(trial_dir / "manifest.json", entries)
