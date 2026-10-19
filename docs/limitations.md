# Scope and current limitations

Research Roost 0.2.0a1 is a local, agent-assisted workspace for PhDs, research
internships and summer/winter research schools. The supported complete experience is a source checkout opened in a
file- and web-capable agent. The Python CLI handles persistence, extraction,
validation, rendering and exports; the agent/user reads research, interprets
requirements, completes assessments and writes substantive documents.

All three families support source-backed annotation, screening, separate
assessment rubrics, reviewed application packets, reports and calendars.
Internship/school source entries are official-site browser handoffs, not
automatic all-web discovery or verified listing/detail adapters. Exact source
coverage and retrieval failures remain visible. See [opportunity modes](opportunities.md).

## Search and disciplines

The profile and workflows accommodate different disciplines and countries.
Articles, books, editions, archives, clinical work, software, data and artistic
outputs are valid profile material; publications or a laboratory are not
universal prerequisites. Built-in discovery is mainly Europe/UK-oriented.
This is not a claim of exhaustive worldwide admissions coverage.

HTML/RSS/Atom/JSON sources can be configured. A source may be blocked or require
a browser. Local query filtering searches a bounded sample of downloaded
postings, not the source's entire catalogue. Check the reported coverage and
the original institution's current requirements. See [sources.md](sources.md).

## Research sources

An agent may inspect accessible public GitHub repositories, publication pages,
Scholar profiles/results, institutional pages and source documents. Availability
depends on its actual browsing tools and the site's access policy. The CLI has
no dedicated GitHub, Google Scholar, ORCID, OpenAlex or Crossref connector.
An ORCID profile field is an identifier, not API integration.

`dossier fetch` archives an explicitly selected URL; it does not automatically
discover all papers, disambiguate authors, reconstruct contributions, execute
research code, import a bibliography or build a research graph. Other research
skills installed in an agent environment are not bundled product capabilities.

## Assessment and application checks

Scores are rubric judgments with explicit coverage and unknowns, not admission
probabilities. Exact quotes, profile references, hashes and archived sources can
be checked mechanically; scientific validity and whether a paraphrase follows
from a source need agent/human review. A same-agent critical pass is disclosed
and must not be described as independent validation.

Source changes make old annotations historical rather than current decision
inputs. External assessment evidence is rechecked when ranking/exporting. This
checks local integrity; it does not establish that the remote page is unchanged
or that a supervisor is currently recruiting. Refresh current claims explicitly.

Application creation produces a preparing packet. PDF output needs a supported
installed engine and fonts; scanned documents need external OCR. Successful
compilation does not replace visual inspection. Existing demonstrations are
fictional and do not establish applicant outcomes or every discipline's quality.

## Distribution, integrations and privacy

The wheel provides CLI commands and packaged workflow/template text. It does not
provide the full repository agent context (AGENTS, router, guides and tools).
Use the checkout for the complete documented agent journey.

Gmail and Notion have local import/export contracts and agent workflows; live
operations require actual connectors and explicit authorisation. No automatic
email sending, portal submission or external publication is performed.

Workspace ignore markers protect newly untracked files. Git ignore rules do not
untrack previously committed personal files. A user-selected backup/export path
is not automatically private; keep personal exports outside public source trees.

See [verification.md](verification.md) for historical checks and the latest
correction record. Local tests are not proof that remote CI or external account
integrations have run.
