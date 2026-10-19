# Source adapters, access and coverage

The portable source registry is `workspace/sources.json`. No hardcoded source list is used by scraping. Use `sources list`, `sources add --file source.json`, `sources toggle ID --enabled false`, and `sources health --source ID`.

## Shipped sources

| Source | Route | Current verification scope |
|---|---|---|
| EURAXESS | R1 filter observed on the official search page | The corrected robots matcher rejects the configured search route under the current `/jobs/*` restriction. Earlier listing/detail observations are historical; direct scraping is currently unavailable. R1 is broader than doctoral admission. |
| jobs.ac.uk | Official PhD search facet | Listing and one complete JobPosting detail ingested live. Parsed institution/country, full description and closing date; funding still requires source review. |
| Academic Positions | Official PhD listing | Visible through web search/browser; direct transport returned HTTP 403. Reported unavailable, with agent/browser/import fallback. |
| FindAPhD | Plain public listing, disabled by default | Primary page and robots inspected. Query-string `/phds/?*` search is disallowed. No claim of a tested full detail pipeline. |
| Official university/programme sources | Browser/search discovery handoff | Query plans cover universities, departments, doctoral schools, supervisors and funders. Register actual verified HTML/RSS/JSON endpoints per institution. |

Checked 2026-10-19; run live health checks for current state. [EURAXESS search](https://euraxess.ec.europa.eu/jobs/search), [jobs.ac.uk search](https://www.jobs.ac.uk/search/), [Academic Positions PhD](https://academicpositions.com/jobs/position/phd), [FindAPhD](https://www.findaphd.com/phds/) are the primary source pages. Precise execution evidence is in [verification.md](verification.md).

The post-fix probe also inspected [EURAXESS robots.txt](https://euraxess.ec.europa.eu/robots.txt):
its longer `/jobs/*` Disallow overrides the shorter `/jobs` Allow. This is an
access limitation to report, not a reason to bypass policy or treat the board as
empty. Prefer accessible original institutional sources for discovery/import.

The built-in board URLs do **not** advertise a verified remote keyword parameter; query filtering is local to the fetched details. A bounded sample of 10 detail requests is not a portal-wide keyword search. Use the agent's `search-plan` queries and original institution pages for broad discovery, plus independently verified remote-query feeds where available.

## HTML adapter

```json
{"id":"example-university","name":"Example University's doctoral vacancies","kind":"html","enabled":true,"url":"https://university.example/vacancies","link_pattern":"university\\.example/vacancies/[0-9]+$","verified_on":"YYYY-MM-DD","notes":"Describe actual scope, filters, pagination and tested fields"}
```

The adapter discovers same-host posting links and explicit rel=next pagination, then fetches bounded details. JSON-LD JobPosting supplies structured metadata when present; otherwise cleaned text and a heading are preserved for agent annotation. Multiple JobPosting objects on one page are rejected rather than merged into one role. Redirects to a different path/identity are not accepted as the original role; requested/final URLs and errors remain visible. A new detail parser should be backed by a representative fixture and a small real probe, with observed limitations.

`{query}` and `{page}` substitution are supported only when the configured endpoint actually implements those parameters. Do not invent filters for recency, funding, degree or country. A sort/limit is not a filter. Missing next-link pagination is a coverage limitation; use a verified `{page}` template or the browser when appropriate.

## RSS/Atom adapter

```json
{"id":"example-feed","kind":"rss","enabled":true,"url":"https://university.example/doctoral-feed.xml","verified_on":"YYYY-MM-DD","notes":"Official feed URL observed in institution documentation"}
```

The adapter accepts RSS item/link and Atom entry/alternate links, then fetches the original details. It does not claim that every university or board has an RSS feed. XML DTD/entity declarations are rejected; response size and page/detail attempts are bounded.

## JSON adapter

```json
{"id":"example-public-api","kind":"json","enabled":true,"url":"https://university.example/public/vacancies?q={query}&page={page}","items_path":"data.items","url_field":"url","title_field":"title","notes":"Illustration only; inspect the real documented endpoint"}
```

Paths are dot-separated object keys (numeric array components are supported). An empty items_path selects a top-level array. The source must be public, GET-readable and actually support the configured filters. Search result descriptions are not treated as verified original documents without fetching their posting URL. Cross-host links from an explicitly configured feed/JSON source may point to an official ATS; transport and robots checks still apply. HTML discovery itself stays on the configured host.

## Discovery and manual import

`kind: discovery` returns a browser/search handoff and never claims successful scraping. An agent can search official sites, inspect full pages and use `opportunity import --file FILE --url ORIGINAL_URL --mode html|text`. This works with any discipline and board without inventing a brittle adapter. A search snippet alone is insufficient; preserve the actual complete page/text.

## Transport and failure semantics

GET only; public-address checks, URL credential rejection, redirect checks, robots policy including wildcard rules, per-origin pacing, Crawl-delay, bounded retries/Retry-After, timeout, 8 MiB responses and validated ETag/Last-Modified cache. No automatic stale-cache response is presented as a live success. Private-address transport is available only as an internal fixture-test injection point, not a CLI bypass. Robots/login/CAPTCHA blocks are reported rather than bypassed.

Reports distinguish listing and detail failures, query mode, discovered/attempted/stored/matching rows, exact fetched pages and bounded coverage. A source with zero discovered links may be empty, changed or browser-rendered; it is not automatically healthy. Health checks inspect discovery; successful detail ingestion is separately verified.

Deadlines may disagree between JSON-LD and visible text. All recognised candidates
are preserved. A visible date-only closing label takes precedence over boilerplate
machine midnight on the same date, but cannot erase an explicit non-midnight
cutoff. Conflicting dates or precise times become unknown until reviewed. Equal
instants expressed in different zones remain consistent. A time without its
timezone stays unknown rather than becoming an all-day deadline. English clock
suffixes and parenthesized times are recognised. Explicit UTC/GMT, CET/CEST and
AoE use their stated fixed offsets; unrecognised zones remain unknown. A generic
parser does not cover every source layout: review the full original page and
add a source-backed annotation when a precise cutoff is stated elsewhere.

Authentication/browser-challenge shells are rejected at detail ingestion and
HTML listing discovery; their health is unavailable rather than `no_links`.
HTML returned as robots.txt is an access failure, including when mislabeled
as plain text. Valid empty policies and 404 responses retain their normal
semantics. See the [independent replay](independent-verification.md).


## Research internships and schools

The shipped registry also includes five official-site discovery entries:
[Microsoft Research](https://www.microsoft.com/en-us/research/careers/),
[EPFL E3](https://eee.epfl.ch/),
[KAUST VSRP](https://admissions.kaust.edu.sa/study/internships),
[Essex Social Science Data Analysis](https://www.essex.ac.uk/short-courses/social-science-data-analysis)
and [Vienna Winter School](https://shs.univie.ac.at/winter-school/).
These official pages were inspected through web/browser sources on 2026-10-19.
They are explicit `kind: discovery` handoffs: no successful automatic listing
adapter or currently open call is implied by inclusion. The agent checks each
actual edition, source requirements and application page, then imports the
complete original evidence. In particular, the inspected Essex 2027 page says
applications are upcoming; it must not be shown as an open call.

`search-plan --family internship|school|all` creates family-specific queries;
`scrape --family school` selects applicable configured sources and preserves
`browser_required` results. A source without family metadata has unspecified
coverage; annotate it explicitly when registering it. Existing workspaces can
run `sources install-builtins` to add missing shipped routes and missing family
metadata for otherwise unchanged shipped URLs. Custom URLs and enabled flags
are preserved.
