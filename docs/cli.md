# CLI reference

Run from this repository with `./roost ...`, or `python3 -m research_roost ...`; installed entry point: `research-roost`. `--workspace PATH` is a global option before the subcommand. An explicit flag overrides `RESEARCH_ROOST_WORKSPACE`, then the fallback `PHD_SEARCH_WORKSPACE`; otherwise the launcher defaults to this repository's ignored workspace. The installed/module entry point defaults to `./workspace` in the caller's directory. Legacy `./phd`, `phd-search` and `python -m phd_search` remain compatible. The full agent experience requires the repository checkout; a wheel provides CLI and workflow/template text only. JSON goes to stdout; errors are structured JSON on stderr. Exit codes: 0 success, 1 failed/incomplete verification, 2 invalid operation/input, 130 interruption.

| Command | Purpose |
|---|---|
| `init` | Idempotent workspace creation; never overwrite an existing profile. |
| `doctor [--online]` | Local schema/profile/tools/integrity and optional source-discovery health. |
| `modes` | Three supported families, their versioned rubrics and workflow routes; no workspace required. |
| `profile show|validate` | Inspect/validate the confirmed candidate profile. |
| `profile import --file PATH` | Validate and back up a replacement profile. |
| `profile fact --claim TEXT --source SOURCE [--id ID]` | Add a new confirmed candidate fact. |
| `profile document --file PATH --category CATEGORY` | Preserve source document + digest + extraction metadata. |
| `sources list|add|toggle|health` | Inspect/register/enable/probe configured public sources. |
| `sources install-builtins` | Add missing shipped sources and missing family metadata for unchanged shipped routes; preserve custom URLs, enabled flags and other settings. |
| `search-plan [--family phd|internship|school|all]` | Build agent search queries from profile topics/countries; defaults to confirmed preferred types, or the legacy PhD mode. |
| `scrape [--source ID] [--query TEXT] [--limit N] [--pages N]` | Fetch a bounded sample; repeat --source for several. |
| `opportunity add URL [--refresh]` | Direct public posting fetch and evidence archive. |
| `opportunity import --file PATH --url URL [--mode html|text] [--source LABEL]` | Ingest a full saved/pasted original. |
| `opportunity list [--status STATUS]` | List observed positions. |
| `opportunity show ID [--text]` | Full record, snapshot/annotation/assessment and optional cleaned text. |
| `opportunity annotate ID --file PATH` | Source-backed normalized metadata/requirements. |
| `opportunity status ID STATUS` | new/shortlist/dismissed/archived organisation state. |
| `opportunity alias ID URL --note TEXT` | Explicitly link a proven alternate URL. |
| `opportunity merge PRIMARY DUPLICATE --note TEXT` | Back up DB and merge confirmed duplicates with history. |
| `screen ID` | Explicit eligibility checks with pass/fail/unknown. |
| `signals` | Literal discovery hints, separate from scientific scores. |
| `assessment packet ID [--out PATH]` | Exact assessment template plus complete source/profile context. |
| `assessment import ID --file PATH` | Validate and retain a substantive agent/human assessment. |
| `rank [--include-failed]` | Rank current assessments, exposing coverage and score interval. |
| `application create ID [--variant NAME] [--documents KINDS...]` | Create an unfinished, versioned preparation packet. |
| `application attach ID --file PATH --kind KIND` | Register original transcript/diploma/writing_sample/portfolio/language_test/reference/other; preserve source digest and bind final review. |
| `application list|show ID` | Inspect tracked applications and event history. |
| `application verify ID [--require-pdf]` | Check final source/claims/review/requirements/artifact consistency. |
| `application render ID [--pdf] [--engine ENGINE] [--template ID]` | Produce editable LaTeX/print HTML and optional actual PDF. |
| `application status ID STATUS --on DATE --note SOURCE [--allow-unknown] [--files RELATIVE_FILES...]` | Record an actual lifecycle transition; submission archives exact reviewed attachments and declares submitted vs supporting files. |
| `application event ID --kind KIND --file JSON` | Record note/contact/follow-up/interview/assessment/reference evidence. |
| `application referees ID --file JSON` | Replace the current referee inventory with dated, permission-aware records. |
| `followup [--application ID] [--draft]` | List stale applications or make local reminder drafts. |
| `interview ID` | Create preparation from actual submitted artifacts; agent completes it. |
| `dossier create --name NAME --kind KIND` | supervisor/lab/programme/funding dossier. |
| `dossier list|show ID` | Inspect research dossiers. |
| `dossier fetch ID URL` | Archive an explicit primary source with text/digest. |
| `gaps` | Aggregate current non-vetoed assessment gaps for the agent's learning plan. |
| `report [--out PATH]` | Standalone filterable HTML dashboard. |
| `export csv|json|calendar|notion [--out PATH]` | Local structured exports. |
| `template list` | Registered, test-compiled custom layouts. |
| `template add ID --file PATH --engine ENGINE` | Register a self-contained LaTeX wrapper after a mandatory test compile. |
| `mail import --file JSON` | Create a review batch from exact connector/user-provided signals. |
| `mail apply BATCH --approve MESSAGE_ID` | Apply explicitly approved signals, idempotently. |
| `backup --out PATH.zip` | Consistent local snapshot outside the active workspace. |
| `restore --file PATH.zip --to NEW_DIRECTORY` | Checksum/path/integrity-checked restore. |
| `reset --scope profile|state|all [--execute]` | Plan or execute a reversible archive/reset. |
| `workflow [NAME]` | List/read the canonical agent instructions. |

Use command-level `--help` for exact required options. Source/profile/assessment/application schemas are in [data-model.md](data-model.md).

`scrape`, `opportunity list`, `rank` and `report` accept `--family phd|internship|school`.
`opportunity add` and `opportunity import` accept `--edition LABEL [--session LABEL]`:
the same real URL can hold distinct annual editions and sessions without merging
their records. Labels are explicit identity context, not evidence that the
institution's call is open. URL lookup is ambiguous when several records apply;
use the returned ID. Refresh an edition-bound alias with matching explicit labels.

See [opportunity contracts](opportunities.md) for enrollment, permissions,
cost components and multiple deadline kinds. Permission validity can include
`valid_from` and `valid_until`; eligibility uses the stated participation period.
Use explicit stable deadline IDs. The primary application deadline is selected
deterministically by ID, independent of array order. Application/registration
entries are required by default; label optional early-bird reminders as
`kind: other, required: false`. Model alternative admissions rounds as separate
edition/session records when they have different eligibility or participation.

An event file must contain `note`; interview_scheduled and assessment_due also require `at`, for example `{"at":"2026-11-20T14:00:00+01:00","note":"User-confirmed invitation"}`. Other event kinds: note, contact_sent, followup_sent, interview_feedback, reference_requested, reference_received. Record only actual messages/actions, not planned drafts.

For actual communication, provide its nonfuture `occurred_on` date, for example
`{"occurred_on":"2026-10-19","note":"Actual message confirmed by the user"}`.
An undated event can be recorded, but recording/import time does not establish
when contact happened. Follow-up timing uses dated communication and actual
status changes. A pending interview/assessment, or the waiting interval after
that scheduled stage, suppresses a generic application-status inquiry.

Referee example: `[{"name":"Confirmed referee","email":"referee@example.invalid","permission_confirmed":false,"requested_on":null,"due_on":"2026-11-15","received_on":null}]`. Permission false is an explicit unresolved action, not consent to contact.

The engine can be used without an agent for state/extraction/export operations. Scientific judgment, paper reading, source interpretation, substantive prose and visual inspection still need the user/agent; commands explicitly report intermediate artifacts rather than simulating a completed phase.
