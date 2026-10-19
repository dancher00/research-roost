#!/usr/bin/env python3
"""Create two entirely fictional opportunity/application journeys through the CLI.

Only the specified new workspace and optional output file are written. No live
source, model, compiler, email service or submission portal is contacted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read(path: Path):
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def demo(workspace: Path, output: Path | None = None) -> dict:
    if workspace.exists():
        raise ValueError("The demo requires a new workspace; existing user work is never overwritten")
    if output is not None and output.exists():
        raise ValueError("The demo output file already exists; choose another path")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY)

    def cli(*arguments):
        result = subprocess.run([sys.executable, "-m", "phd_search", "--workspace", str(workspace), *arguments],
                                cwd=REPOSITORY, env=environment, capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise ValueError(f"CLI command failed ({' '.join(arguments)}): {result.stderr or result.stdout}")
        return json.loads(result.stdout)

    cli("init")
    inputs = workspace / "demo-inputs"
    inputs.mkdir()
    profile = read(workspace / "profile.json")
    fact = "I compared catchment maps and documented uncertainty in a fictional student project."
    profile["identity"].update(name="Alex Fictional", email="fictional@example.invalid")
    profile["research"].update(topics=["catchment mapping"], methods=["spatial analysis"],
                               statement="I study catchment mapping with spatial analysis.")
    profile["facts"] = [{"id": "mapping", "claim": fact, "confirmed": True,
                          "source": "Synthetic fixture only; no real candidate or achievement"}]
    write(inputs / "profile.json", profile)
    cli("profile", "import", "--file", str(inputs / "profile.json"))
    year = date.today().year + 2
    requirements_quote = "Submit a CV and a motivation letter of at most 250 words describing preparation, goals and availability."
    eligibility_quote = "All career stages are eligible. No degree, publication or current-enrolment prerequisite applies."
    kinds = [
        {"type": "research_internship", "family": "internship", "title": "Fictional Catchment Mapping Research Internship",
         "start": f"{year}-06-01", "end": f"{year}-08-15", "application": f"{year}-03-15", "funding": f"{year}-03-01",
         "claim": "The placement develops a reproducible catchment map and records methodological uncertainty.",
         "budget": "Living costs, accommodation and travel are covered; tuition and registration do not apply.",
         "components": {"tuition": "not_applicable", "registration": "not_applicable", "living": "covered", "accommodation": "covered", "travel": "covered"},
         "funding_status": "fully_funded"},
        {"type": "winter_school", "family": "school", "title": "Fictional Winter School in Catchment Modelling",
         "start": f"{year}-01-10", "end": f"{year}-01-16", "application": f"{year - 1}-11-15", "funding": f"{year - 1}-11-01",
         "claim": "The curriculum includes spatial analysis, model comparison and uncertainty communication.",
         "budget": "Registration and accommodation are covered. Living costs and travel are not covered; tuition does not apply.",
         "components": {"tuition": "not_applicable", "registration": "covered", "living": "not_covered", "accommodation": "covered", "travel": "not_covered"},
         "funding_status": "partial"},
    ]
    completed = []
    for item in kinds:
        kind = item["type"]
        text = (f"{item['title']}\nFictional Research Centre\n{item['claim']}\n{eligibility_quote}\n"
                f"Participation: {item['start']} through {item['end']}.\n"
                f"Application: {item['application']}; financial support: {item['funding']}.\n"
                f"{item['budget']}\n{requirements_quote}\n"
                "Country: FI.\nThis is an entirely synthetic offline demonstration, not a real advertisement.\n")
        source = inputs / (kind + ".txt")
        source.write_text(text)
        url = "https://example.invalid/research-roost-demo/" + kind
        values = {"title": item["title"], "opportunity_type": kind, "institution": "Fictional Research Centre",
                  "country": "FI", "start_date": item["start"], "end_date": item["end"],
                  "requirements": {"reviewed": True},
                  "funding": {"status": item["funding_status"],
                              "components": {key: {"coverage": coverage} for key, coverage in item["components"].items()}},
                  "deadlines": [{"id": "application", "kind": "application", "label": "Application", "deadline": item["application"], "required": True},
                                {"id": "funding", "kind": "funding", "label": "Financial support", "deadline": item["funding"], "required": False}]}
        # The country is part of the deliberately fictional fixture, not a
        # country inferred from a domain or the applicant's identity.
        imported = cli("opportunity", "import", "--file", str(source), "--url", url, "--mode", "text")
        record = cli("opportunity", "show", imported["id"])
        annotations = {"values": values, "evidence": {
            key: {"quote": source.read_text().strip(), "evidence_sha256": record["snapshot"]["sha256"]}
            for key in values}}
        annotation = inputs / (kind + "-annotations.json")
        write(annotation, annotations)
        cli("opportunity", "annotate", record["id"], "--file", str(annotation))
        cli("opportunity", "status", record["id"], "shortlist")
        app = cli("application", "create", record["id"])
        directory = workspace / app["data"]["directory"]
        motivation = ("# Motivation\n\n" + fact + "\n\n" + item["claim"] + "\n\n"
                      "I would use this opportunity to improve the way I explain uncertainty in a map and compare alternative "
                      "processing choices. My proposed learning goal is a small, reproducible worked example with explicit "
                      "assumptions and limitations. I would bring the documented choices from my student project into "
                      "discussions, ask for feedback on alternatives and record what changes my interpretation. This plan "
                      "is prospective; it does not imply that a host has approved the project, provided data or awarded "
                      "financial support. The final scope would follow the actual curriculum or placement instructions.\n")
        (directory / "motivation.md").write_text(motivation)
        claims = read(directory / "claims.json")
        claims["coverage_reviewed"] = True
        claims["claims"].extend([
            {"file": "motivation.md", "text": fact, "profile_refs": ["/facts/0"]},
            {"file": "motivation.md", "text": item["claim"], "posting_quotes": [item["claim"]]},
        ])
        write(directory / "claims.json", claims)
        requirements = read(directory / "requirements.json")
        requirements.update(source_quote=requirements_quote, plan_state="reviewed")
        requirements["documents"]["motivation.md"].update(max_words=250, exact_prompt=requirements_quote)
        write(directory / "requirements.json", requirements)
        cli("application", "render", app["id"])
        review = read(directory / "review.json")
        review.update(reviewer="Synthetic demo fixture review; not an independent academic review", verdict="approved",
                      claims_semantically_checked=True, requirements_checked=True, source_integrity_checked=True,
                      document_hashes={name: sha(directory / name) for name in app["data"]["documents"]},
                      support_hashes={name: sha(directory / name) for name in ("claims.json", "requirements.json")},
                      limitations=["All sources, candidate claims and review decisions are fictional offline fixtures; no real submission or scientific validation occurred.",
                                   "Editable HTML and LaTeX exercised; no PDF engine or visual PDF review exercised."])
        write(directory / "review.json", review)
        verified = cli("application", "verify", app["id"])
        for status in ("drafted", "submitted"):
            app = cli("application", "status", app["id"], status, "--on", date.today().isoformat(),
                      "--note", "Synthetic demo lifecycle record only; no actual external submission")
        completed.append({"opportunity_id": record["id"], "application_id": app["id"], "family": item["family"],
                          "type": kind, "status": app["status"], "verification": verified["state"],
                          "packet": str(directory), "synthetic_submission_archive": app["data"]["submission"]["archive"]})
    report_path = output or workspace / "reports" / "modes-dashboard.html"
    report = cli("report", "--out", str(report_path))
    banner = ("<aside style='padding:16px;margin:16px 0;background:#fff4cf;border:1px solid #d9ad45;border-radius:8px'>"
              "<strong>FICTIONAL DEMONSTRATION.</strong> Candidate, hosts, opportunities, review decisions and submission records "
              "are synthetic fixtures. No actual admission, scientific validation or external submission occurred.</aside>")
    report_path.write_text(report_path.read_text().replace("<main>", "<main>" + banner, 1))
    calendar_path = workspace / "reports" / "modes-deadlines.ics"
    cli("export", "calendar", "--out", str(calendar_path))
    result = {"fictional": True, "workspace": str(workspace), "journeys": completed, "dashboard": report,
              "calendar": str(calendar_path), "pdf_exercised": False, "external_actions": False,
              "scope": "Public CLI application flows with synthetic sources, grounded fixture prose, editable rendering, review checks and immutable recorded archives."}
    write(workspace / "reports" / "modes-demo.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="New directory for fictional demo data")
    parser.add_argument("--out", type=Path, help="Optional standalone dashboard path; must not exist")
    arguments = parser.parse_args()
    try:
        result = demo(arguments.workspace.expanduser().resolve(), arguments.out.expanduser().resolve() if arguments.out else None)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc)}) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
