# Adversarial review: PhD Search versus AI Job Search

**Historical pre-fix audit.** See [post-fix verification](../verification-fixes.md)
for the subsequent corrections, regression tests and current alpha scope.

Date: 2026-10-19. Scope: the current local PhD Search implementation and the local `help/ai-job-search` reference; public GitHub project pages were consulted for positioning, not to establish effectiveness.

## Verdict

PhD Search is a useful agent-assisted research workspace with real persistence, provenance, document/lifecycle checks, rendering and exports. Its discipline-independent data model is appropriate. The demonstrated maturity does not yet justify presenting it as a proven turnkey global PhD-search product or a finished 1.0 release.

The previous delivery summary overstated readiness. All 38 existing tests still pass, while adversarial probes reproduce seven defects. A passing synthetic document pipeline establishes an implementation path, not reliable search coverage, correctness under refresh/failure conditions, or applicant outcomes.

Two separate agent contexts reviewed implementation and upstream/product experience. The primary agent independently reproduced the workspace-selection bug and replayed the executable adversarial cases. These are separate review contexts, not cross-model verification or external expert validation. Product implementation files were not changed during the audit.

## Reproducible evidence

- Baseline: `python3 -m unittest discover -s tests -q` — **38 passed**, 7.812 seconds on this audit run.
- `python3 tools/check_workflows.py` — valid, 16 workflows.
- Fresh-workspace init/doctor/profile validation/search plan/rank/report passed. Blank profiles correctly remain unpersonalised, with no fabricated queries or positions.
- A fresh create/render/verify path correctly leaves an unfinished application in preparing and rejects placeholder prose/missing review.
- The separate synthetic example passed its local packet checks and generated a report/calendar. The product reviewer did not exercise live sources, an external account or PDF compilation in this review.
- The earlier release's PDF/live smoke results remain bounded historical evidence in [verification.md](../verification.md); they do not cover the adversarial failures below.

Run the retained reproduction source from the checkout:

```bash
python3 docs/audits/2026-10-19-reproduce.txt
```

The `.txt` file contains executable Python as an audit artifact. It imports the actual implementation and existing synthetic fixture helper, writes only temporary test workspaces, and uses a localhost HTTP server. Captured results: [2026-10-19-results.json](2026-10-19-results.json). The workspace environment-variable issue was reproduced separately with an explicit temporary selection and the repository launcher.

## Confirmed implementation defects

| Priority | Defect and reproduced consequence | Owning code | Required correction |
|---|---|---|---|
| P1 | An expired advert redirects from `/job/1` to `/search`; forwarded conditional headers cause the destination to return 304. The client returns the old advert with its old URL and a fresh observation time. A full second scrape reports `ok`, an advert match and no errors. | [network.py:173](../../phd_search/network.py#L173), [redirect handling](../../phd_search/network.py#L45) | Bind conditional reuse to the resource that produced the response, clear inappropriate validators on identity-changing redirects, and reject a redirected 304 as revalidation of the original advert. |
| P1 | A source changes from self-funded to funded, but the old self-funded annotation still drives a funding failure. A stale-warning gate is added too late; default rank hides the position entirely. | [assessment.py:21](../../phd_search/assessment.py#L21), [staleness gate](../../phd_search/assessment.py#L188), [default filtering](../../phd_search/assessment.py#L285) | Keep obsolete annotations as historical evidence; exclude them from current hard decisions until reverified. |
| P1 | Valid JSON syntax with `validThrough` as an array raises AttributeError. One malformed advert stops the next independent source and saves no scrape run report. | [extract.py:78](../../phd_search/extract.py#L78), [scrape failure boundary](../../phd_search/sources.py#L178) | Validate structured field types, convert boundary failures to source-local errors, continue independent sources and retain a partial run report. |
| P2 | Delete an archived external file after importing a score supported solely by it: the assessment remains `current`, retaining coverage and positive contribution. | [assessment.py:269](../../phd_search/assessment.py#L269) | Recheck all bound external evidence/digests when determining assessment currency and producing decisions/exports. |
| P2 | Modify a fact in the submitted profile archive without updating its manifest. Interview preparation accepts it as the submitted archive and inserts the changed fact. | [applications.py:478](../../phd_search/applications.py#L478) | Validate the submission manifest and digests before reusing archived materials. Ordinary working-draft separation is real, but archive integrity is not enforced at this consumer. |
| P2 | Robots with `Disallow: /jobs/` and a longer `Allow: /jobs/public/` deny a permitted public posting. The custom matcher allows it, but the additional stdlib matcher vetoes it. | [network.py:99](../../phd_search/network.py#L99) | Use one complete policy authority with the correct rule specificity; upstream's matcher already embodies this lesson. |
| P2 | `PHD_SEARCH_WORKSPACE=/tmp/selected ./phd doctor` still selects the repository's default workspace, contrary to the README. Explicit `--workspace` works. | [phd:5](../../phd#L5), [parser default](../../phd_search/cli.py#L38) | Preserve the caller's environment-selected workspace unless an explicit command-line selection overrides it. |

P1 denotes a blocker for dependable advertised search/decision behavior. P2 denotes a consequential correctness/usability issue to fix before presenting the associated guarantee as reliable. The archive corruption reproduction requires a local file modification; it does not establish a remote exploit. No speculative exploit claims are made here.

## What upstream experience was actually transferred

| Upstream operational lesson | PhD Search result |
|---|---|
| Canonical workflows and thin pointers across agent runtimes | Adopted. The router and 16 canonical workflows avoid duplicated personal facts/rules. |
| Personal data in a public fork is dangerous | Improved structurally. Empty profile, ignored personal workspace and tracked instruction files without candidate data. |
| Newly confirmed facts must reach the master profile immediately; tailored drafts are not evidence | Adopted in commands, schemas and agent instructions. |
| Stable identity, cross-run deduplication, precise application-to-archive matching | Real implementation with URL identity and explicit aliases/merges. Different cycles are preserved. |
| Complete posting, original sources, retrieval provenance; unavailable does not mean closed | Adopted in design and run reports, but refresh/cache and malformed-source failures undermine it in the confirmed cases. |
| Drafting and critical review have distinct roles | Adapted to separate phases with honest same-agent disclosure. Upstream's scoped read-only fetch/scoring agents and reviewed tool boundaries were not ported as equivalent runtime enforcement. |
| Compile real PDFs, inspect rendered pages and inspect extracted text | Implemented in workflow and basic build/page/text checks. Rich semantic/layout/ATS assertions still require agent/human work; copied PDF helpers are not all automatically wired into application verification. |
| Exact submitted materials should drive interview preparation | Separate frozen copies and manifests implemented; consumer-side checksum verification is missing. |
| Broad disallow versus specific robots allow | Regressed. The upstream policy helper chooses the longest match directly. |
| Cheap, bounded triage before deep application research | Not fully transferred. Upstream has candidate projection, batch/top limits and backlog selection; current agent ranking lacks an equivalent compact candidate-selection interface. |
| Reuse research with an explicit TTL and reverify claims before shipping them | Dossiers retain sources, but a concrete reuse/freshness protocol is missing and external assessment currency is incomplete. |
| Reusable candidate writing voice and interview examples | Less developed as structured first-class profile material. |
| Custom template assets and declared toolchains | Partial. Current native registration is self-contained LaTeX; Word/Typst and asset-heavy templates are external agent authoring paths. |
| Email signals require review; offer is not acceptance | Implemented in tested local contracts. Connected Gmail/Notion operation has not been demonstrated. |
| Real-user evidence and a short, visible walkthrough | Not yet demonstrated. The sample is explicitly synthetic and useful for engineering verification. |

These differences are substantive. Adapting salary/job-market assumptions into funding/tuition/mobility/doctoral-route questions is appropriate; mechanically copying a two-page job CV or imposing publications/lab methods on all doctorates would be a regression for the stated universal scope.

## Product readiness gaps

1. **The first successful user journey is not demonstrated.** Quickstart starts with the author's absolute local path, does not explain obtaining the repository and agent handoff clearly, and ends with JSON-escaped workflow instructions. An agent can perform the process, but a new user has to infer that execution model.
2. **Universal configuration is stronger than demonstrated search coverage.** The model supports arbitrary disciplines/countries. Shipped live search is mainly European/UK boards, with one successfully ingested live detail in the recorded probe. Built-in keyword queries filter bounded fetched samples locally; they do not search the entire portal by topic. Actual global admissions routes need a precise coverage map and validated university/funder sources.
3. **A wheel is not the complete agent distribution.** It includes CLI/workflow resources, but the workflows refer to repo-only AGENTS, the router skill, docs and `./phd`. Either make the checkout the explicit supported full experience or distribute/install all required agent context portably.
4. **The global audience cannot easily enter.** Main README is Russian-only, while CLI/workflows/docs are English. There is no English entry point or short inline walkthrough. A generated HTML file is helpful, but not a readily visible product demonstration.
5. **Evidence of useful outcomes is absent.** No real candidate has completed the disclosed process in this repository. Time saved, first-result quality, missed opportunities, source accuracy and usability across disciplines have not been measured. Do not substitute test count for those measures.

## How to use the current product

The complete current experience is the repository opened with a file-capable, web-capable AI agent. It is an agent-assisted workspace; the CLI stores, validates and exports the work.

1. Run `./phd init` and `./phd doctor` in the checkout. Until the workspace-selection bug is fixed, choose another workspace explicitly with `./phd --workspace /absolute/path ...`.
2. Give the agent actual source documents and ask it to execute setup. It registers originals, reconciles facts, asks necessary questions, fills/imports the confirmed profile and prepares queries. `profile document` alone preserves a file; it does not semantically populate the profile.
3. Start with a few known original institutional posting URLs or the agent's web discovery. Use built-in scraping as supplemental bounded discovery and verify current source identity and terms.
4. Ask for a source-linked shortlist with funding/eligibility questions. The agent completes annotations and semantic assessment packets; the CLI validates/imports/ranks them. A bare `rank` does not perform missing scientific evaluation.
5. Select an opportunity and request the complete actual document set. The agent writes substantive prose, records requirements/claims/review, renders, visually inspects and verifies. `application create` and `render` alone create/render a preparing scaffold.
6. Submit through the actual institution's route, then record the user-confirmed submission and source/receipt. Track references/interviews/outcomes and regenerate the offline dashboard/calendar. Check source/archive integrity manually pending the identified fixes.

Useful prompts in the current workspace:

> Execute the setup workflow using these candidate documents. Populate the confirmed profile, preserve source links, and ask only for essential missing facts/preferences.

> Find PhD opportunities from this profile. Return a source-linked shortlist with verified deadlines, funding/tuition coverage, eligibility questions, research fit and explicit search coverage.

> Prepare the complete application for this original posting URL. Follow its actual document prompts/limits, ground factual claims, render and verify the final materials, and report unresolved requirements.

## Usefulness and GitHub potential

Expected value is strongest for technically comfortable applicants managing multiple opportunities, source-specific eligibility, deadlines and document versions. The actual benefit is an organised, inspectable application process. Effectiveness for a novice applicant or across every discipline remains unvalidated.

The original [AI Job Search](https://github.com/MadsLorentzen/ai-job-search) presents a public author-reported real-use story and a visible workflow. This is not independent outcome evidence, but it is a stronger demonstration than this repository currently provides. Existing projects such as [PhDHub](https://github.com/D2Simon/PhDHub) and [grad-agent](https://github.com/i-ninte/grad-agent) mean that the generic label “AI PhD assistant” alone is not a distinctive position. Their existence does not establish their quality or market demand.

There is no defensible basis for a star-count or virality forecast. Credible differentiation could be a private, source-backed, discipline-inclusive PhD application workspace with transparent funding/eligibility and exact submission history. It needs a repeatable short demonstration, dependable first value and real applicant feedback to make that claim persuasive.

## Recommended order

1. Fix the seven confirmed defects and add regressions at their actual producer/consumer boundaries.
2. Complete one portable five-minute candidate-document → real posting → useful assessed result journey, with accurate agent/runtime prerequisites and no manual JSON/hash work required from the end user.
3. Validate several real institutional/admission routes and clearly publish what is automated, agent-assisted, blocked or unverified. Preserve the universal core rather than implying all sites are already covered.
4. Add compact candidate/batch selection, explicit source freshness/reuse and reusable writing/interview context before scaling the backlog.
5. Add English-first onboarding, a short authentic walkthrough and consented beta cases across different disciplines. Measure time to first useful shortlist, factual errors/missed requirements and completion friction. Then assess release positioning from evidence.
