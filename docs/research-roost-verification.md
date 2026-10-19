# Research Roost 0.2.0a1 — local verification

Checked 2026-10-19 on Python 3.12.3. This is the current record for the rename,
research internships and research schools. Earlier [PhD-only verification](independent-verification.md)
remains historical, with its original results and source hashes.

| Check | Observed result |
|---|---|
| Full regression suite | **182 passed**, no failures or errors; 52.026 seconds. |
| New public-CLI replay | **56 checks passed**, 11 scenarios, 121 CLI subprocesses; 10.535 seconds. |
| Previous independent public-CLI runner | **72 checks passed**, 72 CLI subprocesses. |
| Workflows and links | All **18** canonical workflows and documentation/image paths valid. |
| Skills | New Research Roost router and legacy alias pass skill validation. |
| Packaging | Built `research_roost-0.2.0a1-py3-none-any.whl`; installed with no runtime dependencies in a new venv. New/legacy commands and modules, init/doctor, modes and new workflows run outside the checkout; imported modules resolve inside the venv. |
| Synthetic complete applications | Research internship and winter school each rendered editable HTML/LaTeX, passed local review verification, reached drafted and recorded a clearly fictional submission with immutable archives. |
| Existing workspace | Schema-1 data migrates with a backup; profile/document/archive bytes remain preserved. Shipped source installation adds entries and missing family metadata without replacing existing settings. |

Checks, subprocess commands and unittest cases are different measurements; they
are not added into one claimed test count. Source hashes and sanitised measured
results are in [the results file](audits/2026-10-19-research-roost-results.json).

## Cross-review and corrections

Implementation was split across model/screening, discovery/workflows,
applications and storage/CLI/exports. Reviewers then examined code written by
other contributors using new synthetic inputs. This exposed and corrected:

- malformed degree/extra/language requirements that could remove a gate or
  break the entire rank operation;
- ignored permission `valid_from` and confirmed future doctoral enrollment
  overlapping a placement that excludes doctoral students;
- alias ingestion that could overwrite another annual edition;
- CSV using a generic extracted cutoff instead of the reviewed application
  deadline, and reordered deadline arrays reassigning calendar event identities.

The final new replay author did not write the eligibility/storage/exports or
application implementation, but did write discovery/workflows. This is fresh
cross-review of those components, not a claim of whole-product author
independence or independent academic review.

## Reproduce

```bash
python3 -m unittest discover -s tests -v
python3 tools/opportunity_check.py --out /tmp/roost-opportunity-report.json
python3 tools/independent_check.py --out /tmp/roost-independent-report.json
python3 tools/check_workflows.py
```

Both public-CLI runners use temporary workspaces and synthetic inputs. The new
runner performs no network access; the previous runner uses a local
non-forwarding HTTP proxy. No personal workspace or test-helper imports are
used. New cases cover enrolled-through-end, excluded/future levels, availability,
permissions, fee waiver versus full support, tuition non-applicability,
funding/application deadline separation, upcoming calls, exact/unknown calendar
times, annual/session identities, family filters/rubrics, stale evidence/profile
and incomplete/revoked review barriers.

Generate the [two-mode fictional example](../examples/modes-report.html):

```bash
python3 tools/modes_demo.py \
  --workspace /tmp/research-roost-modes-demo \
  --out /tmp/research-roost-modes-demo.html
```

The output and workspace must be new. The demonstration does not send anything.

## Bounded live observations

A separate temporary workspace successfully archived the official
[Vienna winter-school page](https://shs.univie.ac.at/winter-school/) and
[EPFL E3 eligibility page](https://eee.epfl.ch/selection-criteria/).
The active agent supplied exact source-backed type annotations for school and
research internship. EPFL's homepage was also archived, but its extracted text
did not establish an internship type and was not promoted to a typed match.
These observations verify raw-page ingestion and annotation, not an open
vacancy, full current application requirements, candidate eligibility or
exhaustive discovery. Generic HTML needs the agent's reviewed interpretation.

The five shipped internship/school entries are explicitly browser handoffs.
No claim of automatically crawling all institutional sources is made.

## Limits

This round did not compile or visually inspect PDFs; both new application modes
rendered editable HTML/LaTeX. Older PDF observations apply only to their recorded
engine/script paths. Remote Python 3.11/3.13 CI jobs were configured, not run
here. Synthetic checks do not establish scientific correctness, admissions
outcomes, every portal layout or worldwide coverage. No real email, referee
request, submission or publication occurred. The release remains alpha.
