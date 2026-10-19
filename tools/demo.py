#!/usr/bin/env python3
"""Build an explicitly fictional, complete research application demonstration."""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phd_search import applications as apps
from phd_search import assessment as assess
from phd_search import exports, profile, render
from phd_search.cli import initialise
from phd_search.core import atomic_write, digest, json_text, now
from phd_search.evidence import ingest_response
from phd_search.network import Response
from phd_search.store import Store


def run(root: Path, target: Path, compile_pdf: bool = False) -> dict:
    if root.exists():
        raise ValueError("Demo workspace must be a new directory; existing data is never overwritten")
    initialise(root)
    candidate = profile.load(root)
    candidate["identity"].update(name="Alex Example — FICTIONAL DEMO", email="alex@example.invalid", location="Example City", timezone="Europe/Stockholm")
    candidate["research"].update(topics=["translation and cultural memory"], methods=["archival comparison", "close reading"], statement="I study how translations shape cultural memory through archival comparison and close reading.")
    candidate["education"] = [{"level": "master", "degree": "MA, Comparative Literature", "institution": "Example College (fictional)", "awarded_on": "2025-06-01",
                               "description": "Thesis on translation choices in two archival collections."}]
    candidate["experience"] = [{"title": "Research assistant", "organisation": "Example Archive (fictional)", "date": "2024–2025",
                                "description": "Compared catalogue records and documented translation variants for a supervised archival project."}]
    candidate["skills"] = ["archival comparison", "close reading", "bibliographic research"]
    candidate["preferences"].update(countries=["SE"], require_full_funding=True)
    candidate["facts"] = [{"id": "thesis", "claim": "My master's thesis compared translation choices in two archival collections.", "source": "Fictional demonstration profile; not a real candidate", "confirmed": True}]
    candidate["notes"] = "FICTIONAL DEMONSTRATION ONLY. No real candidate, institution, position, review, submission, funding or email."
    atomic_write(root / "profile.json", json_text(candidate))
    with Store(root) as store:
        posting = "\n".join(["Doctoral researcher in translation and cultural memory", "Investigate archival sources and translation.",
                              "Applicants need a master's degree.", "Full tuition and a monthly stipend are covered.",
                              "Submit an academic CV and motivation letter.", "Application Deadline: 31 Dec 2099 - 23:59 (Europe/Stockholm)"])
        job = {"@type": "JobPosting", "title": posting.splitlines()[0], "hiringOrganization": {"name": "Example University (fictional)"},
               "jobLocation": {"address": {"addressCountry": "SE"}}, "validThrough": "2099-12-31T23:59:00+01:00", "description": posting}
        markup = '<html><head><script type="application/ld+json">' + json.dumps(job) + '</script></head><body><h1>' + html.escape(job["title"]) + '</h1>' + ''.join('<p>' + html.escape(line) + '</p>' for line in posting.splitlines()[1:]) + '</body></html>'
        record = ingest_response(store, Response("https://university.example/doctoral/translation-demo", markup.encode(), "text/html", {}, now()), source="fictional-demo")
        sha = record["snapshot"]["sha256"]
        annotations = {"values": {"opportunity_type": "project", "requirements": {"reviewed": True, "degree": "master"}, "funding": {"status": "fully_funded", "tuition_covered": True}},
                       "evidence": {"opportunity_type": {"quote": job["title"], "evidence_sha256": sha}, "requirements": {"quote": "Applicants need a master's degree.", "evidence_sha256": sha},
                                    "funding": {"quote": "Full tuition and a monthly stipend are covered.", "evidence_sha256": sha}}}
        record = assess.validate_annotations(store, record["id"], annotations)
        assessment = assess.assessment_template(record, candidate)
        assessment["assessor"] = "Fictional demonstration; mechanical contract illustration, not expert review"
        for name in ("research_fit", "methods", "preparedness"):
            assessment["dimensions"][name].update(score=4, reason="Illustrative overlap between the fictional candidate's archival research and the fictional project.",
                                                  posting_quotes=["Investigate archival sources and translation."], profile_refs=["/facts/0"])
        assessment["strengths"] = ["A directly relevant archival thesis in the fictional profile."]
        assessment["gaps"] = ["Confirm the group's supervision structure and material access."]
        assessment["questions"] = ["What archive access and supervisory feedback are available?"]
        assessment["recommendation"] = "Investigate missing supervision/environment evidence; sample judgment only."
        assess.save_assessment(store, record["id"], candidate, assessment)
        app = apps.create_application(store, record["id"], candidate, document_kinds=["cv", "motivation"])
        directory = root / app["data"]["directory"]
        motivation = ("# Motivation letter\n\nDear doctoral selection committee,\n\n"
                      "I am applying for the doctoral project in translation and cultural memory. "
                      "I would investigate how translation choices affect the interpretation and circulation of archival materials.\n\n"
                      + candidate["facts"][0]["claim"] + " "
                      "That work gave me a concrete basis for connecting close reading with the comparison of primary sources. "
                      "For the proposed doctorate, I would develop a focused comparison of translation decisions across a carefully delimited corpus, "
                      "document the selection criteria, and examine alternative interpretations rather than assuming a single explanatory pattern.\n\n"
                      "The advertised focus on archival sources and translation connects directly with this agenda. "
                      "Before defining the final corpus, I would seek clarification on material access, supervision and the programme's training opportunities. "
                      "These are open questions, not resources or arrangements I assume are already agreed.\n\n"
                      "Thank you for considering my application.\n\nAlex Example\n")
        atomic_write(directory / "motivation.md", motivation)
        claims = json.loads((directory / "claims.json").read_text())
        claims["claims"].extend([{"file": "motivation.md", "text": candidate["facts"][0]["claim"], "profile_refs": ["/facts/0"]},
                                 {"file": "motivation.md", "text": "The advertised focus on archival sources and translation connects directly with this agenda.",
                                  "posting_quotes": ["Investigate archival sources and translation."], "profile_refs": ["/research/methods"]}])
        claims["coverage_reviewed"] = True
        atomic_write(directory / "claims.json", json_text(claims))
        requirements = json.loads((directory / "requirements.json").read_text())
        requirements["source_quote"] = "Submit an academic CV and motivation letter."
        atomic_write(directory / "requirements.json", json_text(requirements))
        rendered = render.render_application(store, app["id"], compile_pdf=compile_pdf)
        review = json.loads((directory / "review.json").read_text())
        review.update(reviewer="Fictional demo contract audit", verdict="approved", claims_semantically_checked=True, requirements_checked=True, source_integrity_checked=True,
                      document_hashes={name: digest((directory / name).read_bytes()) for name in app["data"]["documents"]},
                      support_hashes={name: digest((directory / name).read_bytes()) for name in ("requirements.json", "claims.json")},
                      limitations=["Synthetic example only. No genuine admission, scientific review or submission occurred."])
        atomic_write(directory / "review.json", json_text(review))
        verification = apps.verify_application(store, app["id"])
        if verification["state"] != "pass":
            raise ValueError(json_text(verification))
        apps.transition(store, app["id"], "drafted", occurred_on=date.today().isoformat(), note="Synthetic demonstration review only")
        apps.transition(store, app["id"], "submitted", occurred_on=(date.today() - timedelta(days=20)).isoformat(), note="SYNTHETIC recorded submission, no real action")
        exports.report(store, candidate, target)
        text = target.read_text().replace("<main>", "<main><p style='background:#fff4cf;border:1px solid #e4c35e;padding:15px;border-radius:8px'><strong>FICTIONAL DEMONSTRATION.</strong> These are synthetic candidate, institution, position, funding and submission records.</p>")
        atomic_write(target, text)
        exports.export_csv(store, candidate, root / "reports/tracker.csv")
        exports.calendar(store, root / "reports/deadlines.ics")
        return {"workspace": str(root), "report": str(target), "verification": verification["state"], "rendering": rendered, "fictional": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    print(json_text(run(args.workspace.resolve(), args.out.resolve(), args.pdf)))
