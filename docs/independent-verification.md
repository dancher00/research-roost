# Independent CLI verification — 2026-10-19

Historical PhD-only record. Latest additional functionality and checks:
[Research Roost 0.2.0a1](research-roost-verification.md).

Current local correction record for **0.1.0a2**, on Python 3.12.3.
This supersedes the [0.1.0a1 verification](verification-fixes.md) for the
boundaries below; that earlier record remains available as history.

## Method and findings

Reviewers built new inputs and invoked the public CLI in separate temporary
workspaces instead of reusing the existing test fixtures. An initial network
probe exercised 37 CLI commands across 13 scenarios: 10 passed and 3 failed.
It exposed these additional defects:

- A coarse visible closing date could erase a precise non-midnight cutoff,
  keeping an expired opportunity eligible for longer than the source allowed.
- HTTP 200 authentication or browser-challenge shells could be stored as
  opportunity evidence, or misreported as a listing with no links.
- An HTML challenge served as robots.txt could be treated as a permissive
  robots policy.

The implementation now preserves precise cutoffs and conflicts, checks central
authentication/challenge structures at both ingestion and listing discovery,
and rejects HTML at the robots-policy boundary. Positive fixtures retain real
adverts with ancillary sign-in navigation and valid empty/404 robots policies.

A separate reviewer who had not written production code independently replayed
these cases and discovered a longer authentication shell and the listing-health
distinction. Those variants were also fixed. During a subsequent live official
page import, a parenthesized time such as `27 October 2026 (16:00 CET)` exposed
another extraction gap. Explicit clock formats now preserve their fixed offsets;
an unrecognised or missing zone stays unknown. The reviewer added separate
public-CLI and calendar checks after that change; they did not reproduce this
last formatting gap against the earlier implementation.

## Final local results

| Check | Result and scope |
|---|---|
| Regression suite | **107 tests passed**, no failures, errors or skips. |
| Fresh independent public-CLI replay | **72 checks passed**, no failures; **72 CLI subprocesses**. Own synthetic fixtures and local HTTP; no package-internal imports or old test helpers. |
| Separate first-use journey | **42 CLI commands passed** on the preceding 0.1.0a1 baseline in a clean copied checkout and installed wheel: document preservation, collisions/reimport, workspace selection/move, backup/restore/reset and Git ignore behavior. |
| Separate application probe | **22 checks passed**: CV preservation, synthetic humanities profile, unfinished/review transitions, submitted archive stability and tamper rejection before interview preparation. |
| Clean installation | Built the current 0.1.0a2 wheel, installed without runtime dependencies into a new venv, then ran version/init/doctor and packaged setup workflow outside the checkout. |
| Static validation | Ruff and all 16 workflow/documentation checks passed, including README image paths. |

Command counts, checks and unittest cases are different measurements and are
not added together. Some reviewers of the first-use/application/network probes
had contributed to earlier code; independence there means fresh scenarios and
execution, not complete author independence. The final public replay was
performed by the additional reviewer without production-code authorship.

The real-candidate first-use exercise kept the supplied LaTeX CV, profile and
search state under the ignored private workspace. Import preserved the original
bytes; the active agent filled the semantic profile from document facts and
user confirmations. A CLI import alone does not interpret or validate a CV.
Two official programme pages were archived successfully; a third direct import
reported an unavailable robots policy rather than a successful fetch. Candidate
data and private search results are excluded from this public record.

## Reproduce

From the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 tools/independent_check.py --out /tmp/phd-independent-report.json
python3 tools/check_workflows.py
```

The independent runner checks HTTP/login/challenge and robots boundaries,
deadline precision/conflicts/zones, unknown funding and salary interpretation,
UTC/all-day/unknown calendar exports, unfinished packets and review revocation
before submission recording. It uses a local non-forwarding HTTP proxy with
synthetic responses; it makes no requests to real institutional hosts and
does not edit production files or the user's workspace. Its JSON includes
individual observations, CLI exits, fixture requests and source digests.

Sanitised final measurements and artifact hashes are recorded in
[the results file](audits/2026-10-19-independent-results.json).

## Limits

These checks do not validate admission decisions, scientific judgments, all
disciplines, every portal layout or worldwide search coverage. This round did
not exercise a PDF compiler or visually inspect new PDFs; earlier PDF
observations remain limited to the paths recorded in the historical reports.
Python 3.11/3.13 remote CI jobs were not executed here. No real application,
email, referee request or external publication was sent. This is an alpha
verification record, not a stable-release certification.
