# Post-fix verification — 2026-10-19, 0.1.0a1

Historical record for 0.1.0a1. The latest additional findings, fixes and final
107-test/72-check results are in [independent verification](independent-verification.md).

All ten concrete findings from the two local adversarial audits have corrected
behavior and regression coverage. This record supersedes their open-defect
status, while the original reports/results remain historical evidence.

Three agents implemented separate network/parser, document/privacy and
application fixes; the primary agent fixed assessment currency and reviewed the
combined changes. Another agent checked assessment consumers independently.
These are separate agent contexts, not external or cross-model certification.

## Corrections and observable results

| Finding | Corrected behavior | Regression coverage |
|---|---|---|
| Document basename collision | Different contents retain different immutable original/extraction/metadata versions; repeated import checks existing integrity and does not overwrite. Legacy files remain intact. | `test_privacy_regressions.py`: basename, HTML separation, repeated import, corrupted preserved file and unavailable extraction cases. |
| Reset archive outside ignore | Workspace-local private markers travel with archives; reset upgrades a legacy workspace before moving it. A repository rule also protects old default archive names. Actual temporary Git status exposes no candidate files. | `test_privacy_regressions.py`: all reset scopes, existing ignore preservation, real Git default/custom/legacy archive checks. |
| Redirected 304 resurrects advert | Validators are removed when resource identity changes. A 304 is reusable only for the same cached representation with actual validators; scrape reports identity-changing redirects as partial failures. | `test_network_regressions.py`: direct ETag/Last-Modified positives, full expired scrape, forced/unsolicited 304, alias and cycle-query cases. |
| Stale annotation vetoes new funding | Historical annotations no longer override new extraction in screen/rank/report/calendar. The opportunity stays visible with unknown terms until reverified. | `test_assessment_regressions.py`: self-funded → updated funded source and old deadline cases. |
| Malformed external data aborts independent sources | JSON/JSON-LD types, finite numbers and nesting are checked at entry. An invalid page produces an Error local to that source; good sources continue and the partial run is saved. | `test_network_regressions.py`: malformed nested JobPosting fields, bad/deep/nonfinite JSON and valid structured positives. |
| Deleted external assessment evidence remains current | Ranking/export recheck each referenced file/digest/quote. Missing or modified evidence yields stale, zero usable coverage and no score; restoring exact bytes restores current status. | `test_assessment_regressions.py`: delete/modify/restore, CLI/export and missing-workspace cases. |
| Submitted archive consumed without integrity check | Interview preparation verifies manifest, inventories, all declared files, paths, identity and source/profile bindings. New submissions record the manifest hash; legacy archives receive consistency checks. | `test_application_regressions.py`: each archived file, attachments/external sources, missing files, manifest edits, traversal, legacy positives and working/submitted separation. |
| Specific robots Allow rejected | One authority applies rule specificity, Allow ties, wildcard/encoded paths and product-specific group selection. | `test_network_regressions.py`: longest/tie/specific-group rules, crawl delay, 404/403 and redirect enforcement. |
| Workspace environment ignored | Launcher respects `PHD_SEARCH_WORKSPACE`; explicit `--workspace` overrides it. | `test_privacy_regressions.py`: copied-launcher defaults, environment and explicit paths; also replayed from the clean source copy. |
| Follow-up after recent invitation | Dated status/contact evidence resets timing. Pending interview/assessment stages and their waiting intervals suppress generic inquiries; recording time does not invent a contact date. | `test_application_regressions.py`: invitation/mail dates, pending stages, timezone-equivalent schedules, unknown/future dates and draft idempotence. |

Document paths for new imports have changed. Use the returned locators; existing
files are not migrated. Previously overwritten workspace originals cannot be
recovered by this fix; reimport them from the external original source if needed.
No user's personal workspace was changed during development or verification.

## Checks completed

- **81 tests passed, no failures/errors/skips, 26.925 seconds**, Python 3.12.3.
  This includes the original 38 tests and 43 new regression tests.
- **16 canonical workflows valid**, including English/Russian documentation links.
- `uvx --offline ruff check .` passed.
- Both retained audit reproduction scripts were replayed. All ten behavior
  checks, including a separate launcher selection replay, passed. The old script
  now captures the expected archive rejection instead of stopping at that error;
  its original captured results were not overwritten.
- A clean source copy excluding candidate state, `help/`, caches and build
  outputs completed init/doctor, blank search plan, synthetic document import
  and workflow checks. No author-specific absolute path was required.
- A fresh **0.1.0a1 wheel** was built from that copy, installed without runtime
  dependencies in an isolated Python environment, then exercised outside the
  source checkout. Version, init, doctor and workflow retrieval passed; the
  imported module came from site-packages.
- The post-fix fictional humanities demo completed packet verification and
  submission bookkeeping. Interview preparation verified and used the submitted
  archive. Tectonic compiled CV and motivation; both were one A4 page with the
  expected text. Rasterised pages were visually inspected for clipping/glyphs.
  This is the exercised Latin-text synthetic path, not actual applicant benefit.
- A fresh bounded live check ingested one full jobs.ac.uk posting after finding
  25 listing links. Academic Positions remained HTTP 403. EURAXESS was rejected
  under its current robots policy by the corrected matcher; no bypass was used.

Machine-readable checks, source fingerprint, wheel digest and bounded live
observations: [2026-10-19-fixes-results.json](audits/2026-10-19-fixes-results.json).

## Release scope

The known audited blockers are closed for this local snapshot. It is suitable
for a clearly labelled technical alpha with [documented limitations](limitations.md).
It is not established as a stable 1.0, a complete worldwide index, an autonomous
literature-search engine or a proven admission-outcome tool. Real applicant use
and wider source compatibility still require field validation.

English and Russian onboarding now describe the full source-checkout agent
experience and the smaller wheel/CLI scope. No dedicated academic API connectors
were added or implied. The local version is 0.1.0a1. The CI definition now checks
the installed CLI outside the source checkout; remote CI was not run here.
No repository, release, dashboard or external message was published.
