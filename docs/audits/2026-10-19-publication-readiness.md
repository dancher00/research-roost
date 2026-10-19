# Publication readiness — second adversarial review, 2026-10-19

**Historical review before fixes.** The ten findings below have since been
corrected and checked in [post-fix verification](../verification-fixes.md).
The no-go verdict here describes the reviewed pre-fix snapshot.

## Decision

**No-go for a stable release, public beta, or a recommended working alpha.**
The current code has five confirmed P1 findings and five P2 findings. The seven
findings from the [first audit](2026-10-19-adversarial-review.md) remain open;
this review found three additional defects. Publishing source as explicitly
experimental/WIP is a different decision from claiming product readiness.
This review did not publish anything or change product implementation files.

Three separate agent contexts checked implementation, distribution/onboarding,
and research capability/claims. The primary agent ran the suite, replayed the
old reproductions, independently reproduced the new document and reset faults,
and exercised current live sources and the PDF demonstration. These are separate
agent reviews, not cross-model verification or independent academic validation.
The checkout has no `.git` directory, so there is no commit or remote CI result
to identify as the reviewed release.

## Confirmed release findings

P1 means a blocker for recommending the advertised behavior to applicants.
P2 means a consequential correctness issue to resolve before claiming the
corresponding guarantee. Findings are individual reproduced defects, not a
count of every possible consequence.

| Priority | Finding | Current consequence | Location |
|---|---|---|---|
| P1, new | Original document name collision | Two successful imports of different `transcript.txt` files in the same category receive one destination. The second replaces the first archived original, text and metadata. The original files outside the workspace survive; the first workspace copy does not. | `phd_search/evidence.py:99–100` |
| P1, new | Reset moves personal files outside ignored storage | Default `reset --scope all --execute` renames `workspace/` to sibling `workspace-archived-.../`. `git check-ignore` returns false for its profile; `git status` exposes profile/documents as untracked. A later broad add/commit could include them. No leak or publication occurred in this review. | `phd_search/cli.py:232,243`; `.gitignore:10` |
| P1, retained | Redirected HTTP 304 reuses an old advert | A cached advert redirects to search; the destination's 304 returns the old advert as current. The second full scrape reports `ok`, an old match, and no errors. | `phd_search/network.py:45–50,173–174` |
| P1, retained | Stale annotation still vetoes current funding | An old self-funded annotation overrides a refreshed funded posting. Eligibility fails and default rank hides it. | `phd_search/assessment.py:21–24,188–190,285–288` |
| P1, retained | Malformed structured field aborts other sources | `validThrough` as an array causes AttributeError. The next independent source is never requested and no scrape run report is saved. | `phd_search/extract.py:78`; `phd_search/sources.py:178` |
| P2, retained | Missing external assessment evidence stays current | Deleting its archived supporting file leaves the assessment current with its previous coverage and contribution. | `phd_search/assessment.py:269–270` |
| P2, retained | Submitted archive is trusted without manifest check | Editing the archived profile makes an invented fact appear in the interview packet despite a mismatched manifest. Requires local archive modification. | `phd_search/applications.py:478–488` |
| P2, retained | Specific robots Allow is overridden | A permitted public path is rejected by the additional first-match parser. | `phd_search/network.py:99` |
| P2, retained | Launcher ignores environment workspace | `PHD_SEARCH_WORKSPACE` is overridden by the launcher's default argument; explicit CLI selection works. | `phd:5` |
| P2, new | Follow-up ignores a recent invitation | After an invitation today and interview tomorrow, a 30-day-old submission generates a generic application-update draft and reports 30 days since contact. No message is sent. | `phd_search/applications.py:454` |

Additional privacy limits: callers can deliberately select custom workspace,
backup and export locations inside a checkout. The README should not imply that
every arbitrary output path is automatically ignored. This is related guidance,
not another independently counted defect.

## Verification actually performed

- Primary test run: **38 tests passed, 7.893 seconds**, Python 3.12.3. The code
  reviewer independently ran the same suite successfully. Existing tests do not
  cover the reproduced failures.
- Workflow validator: **valid, 16 workflows**.
- Clean source copy without private workspace, `help/`, or build outputs:
  init, doctor, profile validation, search plan, workflow checks and fictional
  demo passed. No original candidate workspace was used.
- The existing wheel was unpacked and run outside the checkout. Package source
  matched the checkout; init/doctor worked. This was not a new clean build or a
  claim of complete agent installation.
- MIT licence, upstream attribution and vendor licence are present, including
  in the inspected wheel. No attribution blocker was established in this review.
- A new fictional humanities demo completed create/render/verify/submission
  bookkeeping. Tectonic compiled CV and motivation to real PDFs. Both were one
  A4 page; candidate text was extracted and rasterised pages were inspected.
  This validates the exercised synthetic Latin-text path, not real applicant
  effectiveness or arbitrary fonts/layouts. The demo's packet pass must not be
  read as all PDFs being required submission artifacts.
- New bounded live probe: EURAXESS listing returned 200 and 10 links, but its
  sampled detail redirected to search and was rejected; Academic Positions
  returned 403; jobs.ac.uk listing yielded 25 links and one full detail was
  archived. This establishes one current detail-ingestion success, not global
  coverage, funding verification or a personalised useful shortlist.
- No account connectors, real submission, email sending or remote CI were run.

Captured fresh results are in
[2026-10-19-publication-results.json](2026-10-19-publication-results.json).
The JSON contains synthetic/local test material and public source observations,
not the candidate's profile.

## Distribution and claims

1. **Portable onboarding is incomplete.** README quickstart starts with the
   author's `/path/to/research-roost` path. A new reader needs clear checkout and
   agent-start instructions, an English entry point, and a short useful example.
2. **The wheel is only a partial distribution of the agent experience.** Its
   workflows refer to AGENTS, router, docs and tools absent from the wheel.
   Explicitly support the checkout for full agent use or package its context.
3. **Universal model does not establish worldwide source coverage.** The model
   accommodates disciplines and countries; built-in and exercised sources are
   mostly Europe/UK. `--query` filters a bounded fetched sample locally.
4. **Research value is present, but agent-assisted.** Questions/methods/varied
   outputs, supervisor work, tuition/stipend/eligibility and academic documents
   distinguish the intended PhD use case. Scientific reading and writing are
   performed by an active agent/human; `workflow` returns instructions.
5. **No dedicated GitHub/Scholar/ORCID/OpenAlex/Crossref integration exists.**
   A dossier fetch archives an explicit URL. Bibliographic identity resolution,
   import and research graphs are not implemented. Upstream already describes
   GitHub/Scholar reading, so access alone is not differentiation. A dedicated
   academic connector is not a prerequisite for an honestly scoped alpha.
6. **Version 1.0.0 overstates readiness.** There is no disclosed real-candidate
   end-to-end validation or outcome evidence. Synthetic demos are correctly
   labelled and should remain separate from those claims.

## Minimum release gate

1. Fix the five P1 faults and add meaningful regressions at their CLI,
   refresh/redirect, parser and private-storage boundaries.
2. Resolve the five P2 faults before promising the corresponding functionality.
   For any earlier experimental release, disable affected paths or disclose
   precise limitations prominently; labels alone do not repair data loss.
3. Test a documented clean-checkout agent journey; clearly describe the wheel
   scope, source coverage, optional PDF tools and agent prerequisites.
4. Use a prerelease version and publish a concise known-limitations statement.
   Show a real, consented or public-source end-to-end example before claiming
   proven applicant benefit. English onboarding and a visible walkthrough will
   make the public repository assessable.
5. Review the exact future commit contents for personal data, then run checks
   against that release snapshot. A local passing suite is not a remote CI run.

Reproduce the old boundary findings:

```bash
python3 docs/audits/2026-10-19-reproduce.txt
```

Reproduce the new document/reset/follow-up findings (Git required; temporary
repositories/workspaces only):

```bash
python3 docs/audits/2026-10-19-publication-reproduce.py
```

Both scripts report behavior. They are audit artifacts, not passing regression
tests, and their successful process exit does not mean a defect was fixed.
