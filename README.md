<p align="center">
  <img src="assets/mascot/owl-typing.gif" alt="Research Roost owl typing at a computer" width="220">
</p>

# Research Roost

**Find your next research opportunity—and know why it fits.**

Turn your CV and research interests into a source-backed shortlist of **PhDs, research internships and summer/winter schools**, then prepare the application. Built for any discipline, with separate checks for each opportunity type.

[Русский](README.ru.md) · MIT · Python 3.11+ · **Alpha 0.2.0a1**

[![Checks](https://github.com/dancher00/research-roost/actions/workflows/ci.yml/badge.svg)](https://github.com/dancher00/research-roost/actions/workflows/ci.yml)

```text
CV + interests → researcher profile → opportunities + original sources
              → research/learning fit + funding + eligibility
              → application documents → review → submission record
```

Research Roost works alongside a file- and web-capable AI agent. Your agent researches and writes; the local Python CLI saves evidence, checks supporting material and tracks applications. The CLI does not call a model itself.

## Start here

Clone the repository and open its root folder in your AI agent:

```bash
git clone https://github.com/dancher00/research-roost.git
cd research-roost
./roost init
./roost doctor
```

The core CLI uses Python 3.11+ and the standard library, with no extra Python dependencies or model API key. You provide access to an AI agent through your own environment. On Windows, replace `./roost` with `python -m research_roost`.

Give your agent your CV or research documents and this request:

> Read AGENTS.md and follow the setup workflow using my documents. Build a source-backed researcher profile. Ask for missing facts and preferences; leave undecided topics and countries empty. Then help me choose a search mode.

Next, ask for one of these:

| Mode | Example request | What matters |
|---|---|---|
| **PhD** | “Find PhDs matching my research interests.” | Research question, methods, supervisor, admission, funding and fees. |
| **Research internship** | “Find research internships for my level and available dates.” | Project and mentor, enrollment, duration, pay and work permissions. |
| **Summer/winter school** | “Find schools that teach the methods my project needs.” | Learning fit, prerequisites, session dates, fees, travel and accommodation support. |

Then give the agent an original posting URL and ask:

> Prepare my application for this opportunity. Follow its actual document requirements, explain the evidence for fit, flag unknown eligibility or funding terms, and review the completed documents.

Plain-language requests work without slash commands. The agent follows [AGENTS.md](AGENTS.md), the [router](.agents/skills/research-roost/SKILL.md) and [18 workflows](phd_search/resources/workflows/). `./roost workflow setup` displays instructions; it does not populate your profile.

## What makes it useful for research

- **Research fit beyond keywords.** Connect questions, methods and evidenced work to a project, supervisor or learning goal. Different disciplines can use papers, books, software, data or artistic work.
- **Original evidence you can revisit.** Keep source excerpts, retrieval dates and archived material behind assessments. Unknowns remain visible.
- **Funding and eligibility as separate decisions.** Track tuition, stipend, participation fees, travel and housing separately. Schools retain distinct application, funding, registration and payment deadlines.
- **Applications with a history.** Prepare the documents the programme actually requests, review claims and artifacts, and retain versioned submission records after you confirm a real submission.

Scores are rubric judgments, not admission probabilities. Scientific reading, assessment and writing require agent/human judgment.

## Try it without personal data

Generate a fictional example and open the resulting HTML report:

```bash
python3 tools/demo.py --workspace /tmp/roost-demo --out /tmp/roost-demo.html
```

Use a new workspace path. The demo includes synthetic documents, an assessment and application records; it makes no real submission. Also see the checked-in [PhD example](examples/demo-report.html), [internship/school example](examples/modes-report.html) and [example guide](examples/README.md). Download the HTML files to view them in a browser.

## Coverage and privacy

Built-in discovery is mainly Europe/UK-oriented. Add university and funding sources via HTML, RSS/Atom, JSON or browser/manual import. The five shipped internship/school sources are explicit browser handoffs, not automatic crawlers. Configurable disciplines and countries do not imply exhaustive coverage.

Your agent can inspect accessible GitHub repositories, Scholar pages and publications using its browsing tools. This release has no dedicated GitHub/Scholar/ORCID connector. See [sources](docs/sources.md), [opportunity modes](docs/opportunities.md) and [limitations](docs/limitations.md).

Personal profiles, CVs and applications live in the ignored `workspace/`. Keep personal exports and backups outside the source tree; ignore rules do not remove already committed files. There is no automatic email sending or portal submission. Use the repository checkout for the full agent experience; a wheel supplies the CLI and packaged workflow/template text.

## Documentation and checks

[CLI reference](docs/cli.md) · [Profile](docs/profile.md) · [Application review](docs/application-review.md) · [Migration and old command names](docs/migration.md) · [Verification](docs/verification.md)

```bash
python3 -m unittest discover -s tests -v
python3 tools/check_workflows.py
python3 tools/independent_check.py
python3 tools/opportunity_check.py
```

Offline tests use temporary workspaces and local fixtures. Passing tests and fictional examples do not establish real applicant outcomes or current live-site compatibility. PDF generation requires an installed supported engine and fonts.

Workflow design draws on [AI Job Search](https://github.com/MadsLorentzen/ai-job-search). Reused MIT components: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
