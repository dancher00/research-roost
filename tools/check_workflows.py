#!/usr/bin/env python3
"""Check canonical workflow routing, packaged resources and documentation links."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phd_search.profile import validate
from phd_search.sources import validate_source

NAMES = {"setup", "scrape", "rank", "apply", "internship", "school", "supervisor", "funding", "interview", "outcome", "expand", "upskill", "html-report", "add-portal", "add-template", "gmail-sync", "notion-sync", "reset"}


def check() -> list[str]:
    errors = []
    canonical = ROOT / "phd_search/resources/workflows"
    found = {p.stem for p in canonical.glob("*.md")}
    if found != NAMES:
        errors.append(f"Workflow set differs: missing={NAMES-found}, unexpected={found-NAMES}")
    router = (ROOT / ".agents/skills/research-roost/SKILL.md").read_text()
    for name in NAMES:
        text = (canonical / (name + ".md")).read_text() if name in found else ""
        if len(text.split()) < 120:
            errors.append(f"Workflow {name} is incomplete")
        if name + ".md" not in router:
            errors.append(f"Workflow {name} missing from skill router")
        pointer = ROOT / ".claude/commands" / (name + ".md")
        if not pointer.exists() or f"phd_search/resources/workflows/{name}.md" not in pointer.read_text():
            errors.append(f"Claude pointer missing/outdated for {name}")
        elif len(pointer.read_text().split()) > 120:
            errors.append(f"Claude command {name} duplicates workflow instead of pointing to it")
    expected = {"motivation", "statement_of_purpose", "research_statement", "proposal", "supervisor_email", "portal_answers", "portfolio"}
    actual = {p.stem for p in (ROOT / "phd_search/resources/templates").glob("*.md")}
    if actual != expected:
        errors.append("Application template resources do not match the document contract")
    profile = json.loads((ROOT / "phd_search/resources/profile.example.json").read_text())
    errors.extend(validate(profile))
    for source in json.loads((ROOT / "phd_search/resources/sources.example.json").read_text())["sources"]:
        try:
            validate_source(source)
        except Exception as exc:
            errors.append(str(exc))
    paths = [ROOT / "README.md", ROOT / "README.ru.md", ROOT / "AGENTS.md", ROOT / "CLAUDE.md", ROOT / "THIRD_PARTY_NOTICES.md", *ROOT.glob("docs/*.md")]
    for path in paths:
        markup = path.read_text()
        links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", markup)
        links.extend(re.findall(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", markup, re.I))
        for link in links:
            if re.match(r"\w+://", link) or link.startswith("#"):
                continue
            target = link.split("#", 1)[0].strip("<>")
            if not (path.parent / target).exists():
                errors.append(f"Broken local link: {path.relative_to(ROOT)} -> {target}")
    return errors


if __name__ == "__main__":
    errors = check()
    print(json.dumps({"valid": not errors, "workflows": len(NAMES), "errors": errors}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(errors))
