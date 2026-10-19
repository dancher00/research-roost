from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class Error(Exception):
    """An actionable error safe to show at the CLI boundary."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def read_json(path: Path) -> dict | list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Error(f"Cannot read JSON {path}: {exc}") from exc


def atomic_write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value.encode("utf-8") if isinstance(value, str) else value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise Error("Expected an absolute http(s) URL without embedded credentials")
    try:
        port = parts.port
    except ValueError as exc:
        raise Error("Invalid URL port") from exc
    host = parts.hostname.encode("idna").decode().lower()
    if ":" in host:
        host = f"[{host}]"
    if port and (parts.scheme, port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    # Preserve all identity-bearing parameters; remove only recognised tracking.
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}]
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(query), ""))


def slug(value: str) -> str:
    plain = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")
    return (plain[:64] or "item") + "-" + digest(value)[:8]


def contained(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target == root.resolve() or not target.is_relative_to(root.resolve()):
        raise Error("Path must refer to a file within the selected workspace directory")
    return target


def resource(name: str) -> Path:
    return Path(__file__).parent / "resources" / name


def workspace(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not (root / "profile.json").is_file() or not (root / "phd-search.sqlite3").is_file():
        raise Error(f"Workspace is not initialised: {root}. Run: python3 -m research_roost --workspace '{root}' init")
    return root
