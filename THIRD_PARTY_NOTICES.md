# Third-party components and attribution

The workflow design was informed by the local `help/ai-job-search` reference, upstream [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search). Its MIT copyright and licence are retained in `phd_search/vendor/LICENSE`.

Reused components, copyright (c) 2026 Mads Lorentzen:

- `phd_search/vendor/posting_guard.py`, from upstream `tools/posting_guard.py`: text/HTML cleaning and advisory integrity findings.
- `tools/verify_pdf.py`, from upstream `tools/verify_pdf.py`: optional PDF page/text checks.
- `tools/verify_layout.py`, from upstream `tools/verify_layout.py`: optional rendered-layout diagnostics.

The native Research Roost transport, storage, academic data model, CLI, application lifecycle, exports, research functions, tests and doctoral workflow texts are implemented in this repository. The upstream candidate profile, Danish-market search tools and unrelated REA project are not copied into the personal workspace or required at runtime.
