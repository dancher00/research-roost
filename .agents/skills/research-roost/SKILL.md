---
name: research-roost
description: Search and assess PhD opportunities, research internships, summer/winter schools and research training in any discipline. Build a source-backed researcher profile, check funding and eligibility, research supervisors or training fit, prepare applications and track outcomes. Use for doctoral search, research internships, seasonal schools, academic applications, поиск PhD, научные стажировки, летние и зимние научные школы, and the workspace workflows.
---

# Research Roost

Resolve the repository root three directories above this file. Read its `AGENTS.md`. Use `./roost` there or the installed `research-roost` executable with an explicit `--workspace`. A command recipe is an instruction to the agent, not a standalone shell slash command. Ordinary language requests invoke the same workflows.

## Route by task

| Intent or alias | Canonical workflow under `phd_search/resources/workflows/` |
|---|---|
| Set up/import candidate profile, `/setup` | `setup.md` |
| Search new opportunities, `/scrape` | `scrape.md` |
| Research internship search and applications, `/internship` | `internship.md` |
| Summer/winter schools and research training, `/school` | `school.md` |
| Assess/rank positions, `/rank` | `rank.md` |
| Prepare/tailor an application, `/apply` | `apply.md` |
| Research a supervisor/lab/programme, `/supervisor` | `supervisor.md` |
| Check funding, fees or eligibility, `/funding` | `funding.md` |
| Prepare an interview/mock interview, `/interview` | `interview.md` |
| Track submission/response/reference/follow-up, `/outcome` | `outcome.md` |
| Enrich profile from evidence, `/expand` | `expand.md` |
| Skill-gap/readiness plan, `/upskill` | `upskill.md` |
| Offline dashboard/calendar, `/html-report` | `html-report.md` |
| Add a portal/feed, `/add-portal` | `add-portal.md` |
| Register custom document layout, `/add-template` | `add-template.md` |
| Review Gmail status signals, `/gmail-sync` | `gmail-sync.md` |
| Publish pipeline to an authorised Notion database, `/notion-sync` | `notion-sync.md` |
| Archive/reset local profile or search state, `/reset` | `reset.md` |

Read only the active workflow and its required references. Preserve the user's language; document language follows the actual programme prompt or the confirmed profile choice. Do not assume every doctorate needs a proposal, publications, a lab, a master's degree, a two-page CV, tests, or prior supervisor contact.

## Execution

1. Inspect local state with `./roost doctor` when setup is unknown. Run init only if needed. Load the profile once; ask for essential missing information early while continuing independent work.
2. Prefer original institution/admissions/funding pages. Use board CLIs where usable, otherwise available web search/browser tools and `opportunity import`. Label bounded search coverage and failure modes.
3. Use the active agent to perform research, semantic assessments and substantive drafting. CLI packets provide complete context and evidence bindings; fill them rather than claiming the scaffold is finished. No hidden model invocation or external private-profile upload occurs in the CLI.
4. Keep source-linked facts and proposals separate. Store confirmed new candidate evidence in the profile. Verify publications and current institutional rules from primary sources before relying on them.
5. Perform drafting and critical review as separate phases. Use the current runtime unless the user explicitly requests delegation. Do not claim independent review when one agent performed both phases.
6. Finish authorised research/drafting/checks before returning the result. Ask only for missing material decisions or explicit external action authority. A template's suggested checkpoint does not override authorisation already given in the conversation.

Full flags: `./roost --help`, `./roost COMMAND --help`. Canonical schemas and limitations: `docs/data-model.md`, `docs/rubric.md`, `docs/sources.md`, `docs/application-review.md`.
