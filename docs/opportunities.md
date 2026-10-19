# Opportunity families

ResearchRoost supports doctoral opportunities, research internships and research-relevant schools in one private workspace. Each family has its own discovery queries, eligibility checks and assessment rubric. Family selection does not manufacture source coverage, turn a keyword hit into research fit or submit an application.

| Family | Exact `opportunity_type` values | Main decision |
|---|---|---|
| `phd` | `project`, `doctoral_programme`, `studentship`, `doctoral_network`, `scholarship`, `supervisor_led`, `other` | Does this doctoral route support the candidate's research and actual admission/funding conditions? |
| `internship` | `research_internship` | Can the candidate make a feasible research contribution during this placement and meet enrollment, timing and permission rules? |
| `school` | `summer_school`, `winter_school`, `research_school`, `training_school`, `field_school`, `short_course` | Does this specific training programme advance a research learning goal at an appropriate level and affordable cost? |

The older types remain doctoral routes. In particular, a legacy `scholarship` is not automatically reclassified as a school scholarship. Schools include summer and winter editions but use the same school rubric. All families accommodate humanities, social sciences, natural sciences, medicine, engineering, arts and practice research. A lab, publications, an MSc or a named PI are not universal prerequisites.

## Choose a mode

Ask the agent to use `/internship`, `/school`, or the same request in ordinary language. The packaged canonical workflows are [internship](../phd_search/resources/workflows/internship.md) and [school](../phd_search/resources/workflows/school.md). They cover discovery through eligibility, research/training evaluation, applications and reports.

Save confirmed types in `preferences.opportunity_types`. For example:

```json
{"opportunity_types": ["research_internship", "summer_school", "winter_school"]}
```

This is a fragment of the preferences object, not a replacement profile. Import a complete, validated profile through `./roost profile import --file PATH`. Do not infer the choice from the user's current degree. An existing empty type selection retains PhD discovery, preserving the earlier product behaviour.

For one-off exploration without editing saved preferences:

```bash
./roost search-plan --family internship
./roost search-plan --family school
./roost search-plan --family phd
./roost search-plan --family all
```

Plans return family-labelled queries for the active agent/search engine. They do not perform a live search. Without confirmed topics/keywords they return `profile_required`, no personalised queries and only generic templates. No countries, enrollment status, availability or funding needs are filled in automatically. `--family all` requests three discovery families; exact selected types and each original advert still control whether an actual opportunity is appropriate.

Use `--family phd|internship|school` with `scrape`, `opportunity list`, `rank` and `report` for a focused view. A source still needs actual suitable postings: built-in doctoral boards do not become comprehensive internship or school catalogues. The agent can use official hosts, universities, institutes, archives, museums and societies and accurately identified manual imports. See [source coverage and limitations](sources.md).

## Preserve the actual edition

Annual programmes may reuse one URL. Add/import `--edition LABEL` (or `--session LABEL`) to keep separate intake identities while retaining the original source URL. For example, `./roost opportunity add ORIGINAL_URL --edition 2027-summer`. Use the opportunity ID when several editions share a URL: URL-only lookup is ambiguous. The label distinguishes records; it does not establish that this edition exists or is open. Check the official current page, dates, host and reference. Never invent a URL query parameter to bypass deduplication.

Retain the actual application state as `open`, `upcoming`, `closed`, `rolling` or `unknown` only when supported by original evidence. A future deadline is not proof of open recruitment. Unknown or blocked source access is not an empty result. Do not migrate an old cycle into a new one by changing its label.

## Dates and deadlines

The legacy `deadline` remains readable. New `deadlines` entries distinguish cutoff roles. Each entry has a `kind` and a `deadline` (source string or parsed object), with optional unique `id`, human `label` and boolean `required`. Supported kinds are `application`, `funding`, `registration`, `payment`, `reference` and `other`. Use `funding` for a scholarship/travel-grant application and an explicit `other` label for an acceptance or abstract cutoff. Missing `required` defaults to true for application/registration and false for the other kinds; confirm whether each cutoff is actually mandatory for this route. Preserve raw wording, original precision and timezone; never supply a fabricated UTC time.

Application and scholarship deadlines can be different, as can early/regular registration, poster submission and acceptance. Keep separate entries instead of overwriting one with another. A later registration deadline cannot reopen a closed scholarship or required application. Calendar/report labels must make each role visible. Event start/end dates describe attendance or employment; they are not application deadlines.

`start_date` and `end_date` are ISO dates; `duration_days` and legacy `duration_months` describe sourced duration. `mode` is `onsite`, `online`, `hybrid` or `unknown`. Optional `programme_id`, `edition` and `session_id` preserve source identity; edition/session labels are distinct from proof of a current open call.

## Enrollment, availability and permissions

Only apply requirements actually stated by the host or organiser. For internships, `requirements.enrollment` can contain `allowed_levels`, `excluded_levels`, `required`, `through_end` and `return_to_study`; work authorization and home-institution approval are separate requirements. Schools may accept students, graduates, practitioners or several levels. Do not impose a doctoral enrollment rule on every school.

Candidate education entries may carry `enrollment` with a sourced, confirmed status (`enrolled`, `completed`, `withdrawn`, `on_leave`, `unknown`) and known start/end dates. An `in_progress` degree alone does not prove enrollment through a future placement's end. Confirmed preferences may contain availability windows and sourced `return_to_study`, `work_authorization` and `home_approval` facts. Preserve jurisdiction/validity limits where relevant. Absence means unknown, never automatic permission or a negative judgment.

Screen the exact dated requirements against those facts. Fixed event/placement dates outside confirmed availability are a real conflict. Missing end dates, ambiguous overlap, incomplete enrollment evidence and unverified work authorization need investigation. A research score does not override a confirmed eligibility conflict.

## Funding components

Keep `funding.status` (`fully_funded`, `partial`, `self_funded`, `unknown`) separate from specific coverage. `funding.components` may record `tuition`, `registration`, `living`, `accommodation` and `travel`. Each has `coverage` (`covered`, `partial`, `not_covered`, `not_applicable`, `unknown`) and optional sourced amount, currency, period, basis and conditions. Supported periods include day, week, month, year and total. Compare only comparable currency, period and gross/net basis.

A free registration fee is not a fully funded trip. An internship salary does not establish visa, travel or housing coverage. A school need not have doctoral tuition at all: explicitly inapplicable costs differ from unknown costs. Record scholarship competition, eligibility and separate deadlines. Official coverage, estimated costs and user budget preferences must stay distinct. Follow the [funding workflow](../phd_search/resources/workflows/funding.md).

## Fit and application documents

Generate `./roost assessment packet ID` and complete the actual bound family rubric. See [rubrics](rubric.md). PhD, internship and school scores belong to different comparison groups; do not present them as a single scientific ranking. Missing evidence stays null, with coverage and an unknown interval. `/upskill` groups gaps by family so intended school learning does not become an invented PhD deficiency.

Use `/apply` for the actual official prompts. Internships may need an academic CV, project motivation, portfolio and enrollment evidence; schools may need learning goals, an abstract/poster, prerequisites and a separate funding statement. Use existing document kinds such as `motivation` and `portal_answers`, and attach authentic supporting documents. Do not require a PhD proposal, publications or supervisor outreach unless the opportunity requires it. The agent writes substantive content and evaluates primary works; no new automatic paper/PI or Scholar connector is implied.

Every family retains evidence-bound claims, critical review, artifact verification and versioned submission archives. A generated scaffold is unfinished. Local preparation never sends email, pays fees, registers attendance or submits a portal form. Record actual submissions and outcomes only after user confirmation.


Permission confirmations may specify `valid_from` as well as `valid_until`.
Screening compares both bounds with the stated participation dates. Confirmed
future enrollment overlapping the placement is also considered when a degree
level is excluded.

Use explicit stable IDs for named deadlines. `primary_application` selects the
application entry deterministically by ID; reordering an array cannot reassign
calendar events. Alternatives with different participation or eligibility
belong to distinct edition/session records. Optional early-bird reminders can
use `kind: other, required: false`.
