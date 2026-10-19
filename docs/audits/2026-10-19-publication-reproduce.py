"""Reproduce additional release findings in temporary workspaces only.

Run from any directory with Python 3.11+ and Git installed. No source checkout
state, candidate workspace, external account or public service is modified.
The JSON reports observed behavior; exit zero does not mean the defects pass.
"""
from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

def run() -> dict:
    from phd_search import applications as apps
    from phd_search.core import digest

    results = {}
    with tempfile.TemporaryDirectory(prefix="phd-publication-reproduce-") as directory:
        base = Path(directory)
        checkout = base / "checkout"
        checkout.mkdir()
        shutil.copy2(REPO / ".gitignore", checkout / ".gitignore")
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)

        def cli(*args):
            completed = subprocess.run(
                [sys.executable, "-m", "phd_search", "--workspace", str(checkout / "workspace"), *args],
                cwd=REPO, capture_output=True, text=True, check=True,
            )
            return json.loads(completed.stdout)

        cli("init")
        source_a = base / "institution-a" / "transcript.txt"
        source_b = base / "institution-b" / "transcript.txt"
        source_a.parent.mkdir()
        source_b.parent.mkdir()
        source_a.write_text("First original academic transcript.\n")
        source_b.write_text("Different second academic transcript.\n")
        first = cli("profile", "document", "--file", str(source_a), "--category", "transcripts")
        second = cli("profile", "document", "--file", str(source_b), "--category", "transcripts")
        root = checkout / "workspace"
        results["original_document_collision"] = {
            "registered_paths_collide": first["file"] == second["file"],
            "first_digest": first["sha256"],
            "stored_digest": digest((root / first["file"]).read_bytes()),
            "second_digest": second["sha256"],
            "first_bytes_preserved_in_workspace": any(
                path.is_file() and path.read_bytes() == source_a.read_bytes()
                for path in root.rglob("*")
            ),
            "external_source_files_preserved": source_a.is_file() and source_b.is_file(),
        }

        reset = cli("reset", "--scope", "all", "--execute")
        archive = Path(reset["archive"])
        git_base = ["git", "-c", "core.excludesFile=/dev/null", "-C", str(checkout)]
        ignored = subprocess.run(
            [*git_base, "check-ignore", "--no-index", str(archive / "profile.json")],
            capture_output=True, text=True,
        )
        status = subprocess.run(
            [*git_base, "status", "--short", "--untracked-files=all"],
            capture_output=True, text=True, check=True,
        )
        results["reset_archive_outside_ignore"] = {
            "archive_name": archive.name,
            "archive_profile_ignored": ignored.returncode == 0,
            "untracked_paths": status.stdout.splitlines(),
            "commit_or_publication_performed": False,
        }

    fixtures = runpy.run_path(str(REPO / "tests" / "test_workflows.py"))
    case = fixtures["WorkspaceCase"]()
    case.setUp()
    try:
        application = case.reviewed_application()
        today = date.today().isoformat()
        submitted = (date.today() - timedelta(days=30)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat() + "T12:00:00+00:00"
        apps.transition(case.store, application["id"], "drafted", occurred_on=today, note="Synthetic review")
        apps.transition(case.store, application["id"], "submitted", occurred_on=submitted, note="Synthetic attestation")
        apps.transition(case.store, application["id"], "interview", occurred_on=today, note="Invitation today")
        apps.record_event(case.store, application["id"], "interview_scheduled", {"note": "Invitation today", "at": tomorrow})
        suggestions = apps.followups(case.store, case.candidate, identifier=application["id"], draft=True)
        results["followup_after_recent_invitation"] = {
            "invitation_date": today,
            "scheduled_interview": tomorrow,
            "suggestion_count": len(suggestions),
            "reported_days_since_contact": suggestions[0]["days_since_contact"] if suggestions else None,
            "draft": Path(suggestions[0]["file"]).read_text() if suggestions else None,
            "messages_sent": False,
        }
    finally:
        case.doCleanups()
    return results


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
