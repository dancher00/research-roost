#!/usr/bin/env python3
"""Explicit low-volume live smoke check; never writes into the user's active pipeline."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phd_search.cli import initialise
from phd_search.core import atomic_write, json_text, now
from phd_search.network import Client
from phd_search.sources import health, scrape
from phd_search.store import Store


def run(root: Path) -> dict:
    initialise(root)
    with Store(root) as store:
        client = Client(root, timeout=12)
        result = {"checked_at": now(), "scope": "Discovery for three boards and at most one detail attempt for each enabled direct source; not exhaustive compatibility",
                  "health": health(root, client, ["euraxess", "jobs-ac-uk", "academicpositions"])}
        result["scrape"] = scrape(store, client, sources=["euraxess", "jobs-ac-uk"], query="", limit=1, pages=1)
        result["ingested"] = [{"id": r["id"], "url": r["url"], "sha256": r["snapshot"]["sha256"],
                               "title": r["data"]["title"], "institution": r["data"].get("institution"),
                               "country": r["data"].get("country"), "deadline": r["data"].get("deadline"),
                               "description_characters": len(r["data"].get("description", "")), "method": r["data"]["extraction"]["method"]} for r in store.list()]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keep-evidence", type=Path, help="Preserve the isolated evidence workspace at a new path")
    args = parser.parse_args()
    if args.keep_evidence:
        if args.keep_evidence.exists():
            parser.error("--keep-evidence must be a new directory")
        result = run(args.keep_evidence.resolve())
        result["evidence_workspace"] = str(args.keep_evidence.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="phd-live-check-") as temporary:
            result = run(Path(temporary))
        result["evidence_workspace"] = None
    atomic_write(args.out, json_text(result))
    print(json_text({"path": str(args.out), "health": result["health"], "ingested": len(result["ingested"])}))
