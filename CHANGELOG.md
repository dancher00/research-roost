# Changelog

## 0.2.0a1 — 2026-10-19

- Rename the product and Python distribution to **Research Roost**. Add
  `research-roost`, `./roost`, `python -m research_roost` and the renamed router;
  retain former entry points and workspace-variable fallback.
- Add research internships and summer/winter/training/field schools with
  family-specific search plans, eligibility, versioned assessment rubrics,
  application prompts and frozen rubric snapshots.
- Check dated enrollment, excluded levels, return to study, availability,
  duration and source-linked permissions. Preserve unknowns and reject malformed
  requirements before they can alter screening or poison ranking.
- Distinguish tuition, registration, living, accommodation and travel coverage;
  support explicit non-applicability and separate funding deadlines.
- Retain multiple deadline kinds, participation dates, cycle/session identities,
  family-filtered reports and detailed tracker/calendar exports.
- Migrate schema-1 databases transactionally with a backup, retaining IDs and
  references. Preserve calendar UIDs and reject cross-cycle alias overwrites.
- Add five official-site discovery handoffs, additive source installation,
  two complete fictional application demonstrations and new public-CLI checks.

## 0.1.0a2 — 2026-10-19

Independent CLI probes with new datasets exposed additional boundary cases.

- Preserve an explicit non-midnight deadline when the visible page states only
  its date; conflicting exact times and times without zones remain unknown.
- Preserve all deadline candidates after a conflict rather than accepting a
  later label as if the conflict disappeared.
- Preserve explicit parenthesized/suffixed clock times, CET/CEST and AoE
  offsets; unrecognised timezones remain unknown.
- Reject authentication/browser-challenge shells as opportunity evidence while
  allowing genuine adverts with ordinary sign-in navigation.
- Reject HTML/browser-challenge responses at the robots policy boundary.
- Add regression coverage and an independent reviewer replay for these cases.

## 0.1.0a1 — 2026-10-19

Initial alpha designation after two local adversarial reviews. The earlier local
1.0.0 label did not represent a published stable release.

### Correctness fixes

- Preserve separate original document versions when basenames collide; keep
  original, extracted text and metadata separate, with safe repeat imports.
- Keep reset archives private through portable local ignore markers and a rule
  covering previously created default archives.
- Respect environment-selected workspaces, with explicit CLI flags taking priority.
- Bind conditional HTTP reuse to the same resource; strip validators across
  identity-changing redirects and reject unqualified 304 responses.
- Resolve robots rules through one authority with longest-path and Allow-tie
  precedence, preserving product-specific groups and wildcard rules.
- Validate external JSON/JSON-LD types and nesting at entry so malformed pages
  produce local source failures while independent sources and run reports survive.
- Exclude obsolete annotations from current screening, ranking and exports.
- Revalidate external assessment evidence at use; missing/changed evidence makes
  the assessment stale and removes its usable score and coverage.
- Verify submitted archives before interview preparation, including manifest
  anchors for new submissions and full inventory/hash checks for legacy archives.
- Base follow-up timing on dated communication and status evidence; suppress
  generic inquiries around scheduled interview/assessment stages.

### First-use documentation

- English entry point and separate Russian guide with portable first-run steps.
- Explicit distinction between the full checkout-based agent workflow and the
  CLI/workflow text distributed in a wheel.
- Clear limits for board coverage, academic sources, agent judgments and
  user-selected private exports. No new academic API connectors are claimed.
- Installed CLI CI smoke check runs outside the source checkout.

Regression tests and post-fix verification accompany the changes. They do not
establish real applicant outcomes or exhaustive live-source compatibility.
