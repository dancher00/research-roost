# Research Roost migration and compatibility

Research Roost 0.2.0a1 is the new name and distribution of the former PhD Search
workspace. It adds research internships and summer/winter research schools;
existing doctoral workflows remain supported.

| Interface | Primary name | Compatible former name |
|---|---|---|
| Repository slug | `research-roost` | Existing checkout paths remain usable. |
| Python distribution | `research-roost` | Previous release artifacts remain historical. |
| Installed command | `research-roost` | `phd-search` ships as an alias. |
| Checkout launcher | `./roost` | `./phd` remains usable. |
| Python module | `python -m research_roost` | `python -m phd_search` remains usable. |
| Agent router | `.agents/skills/research-roost/SKILL.md` | The former skill path forwards to the canonical router. |
| Default workspace | `RESEARCH_ROOST_WORKSPACE` | `PHD_SEARCH_WORKSPACE` is a fallback. |

An explicit `--workspace` overrides both environment variables. The checkout
launchers default to their own `workspace/`; installed/module entry points
default to `workspace/` in the caller's directory. No global agent configuration
or default research interests are changed by the rename.

## Existing data

The private `workspace/`, profile documents and submitted archives keep their
existing paths. The internal implementation remains `phd_search`; the public
module delegates to it. The database filename and primary calendar UID domain
stay unchanged, preserving references and existing calendar subscriptions.
The HTTP user-agent retains its original product token so the rename does not
silently change robots group selection.

Database schema 2 adds a separate identity key for editions/sessions and removes
URL-only uniqueness. Opening a schema-1 workspace first creates
`backups/before-schema-2-*.sqlite3`, then migrates inside a transaction and checks
foreign keys. The original opportunity IDs, application relations, evidence
and archived submission bytes remain unchanged. A failed migration rolls back.
Use the backed-up database with older releases; those releases do not support
schema 2. Profile and source JSON schema 1 remains readable with new fields
optional.

An original URL can now have explicit `--edition 2027 --session winter` identity
labels. Reimporting the same labels updates that record; another edition stays
separate. Labels do not certify source dates or admission status. Lookup by an
ambiguous URL requires an ID. Unlabelled ingestion through an edition-bound
alias is rejected instead of overwriting a different cycle.

## Add the new sources and inspect modes

```bash
./roost doctor
./roost sources install-builtins
./roost modes
./roost search-plan --family internship
./roost search-plan --family school
```

Source installation is additive. Custom URLs and enabled flags stay intact;
unchanged shipped routes can receive missing descriptive family metadata.
The five new official sources are explicit browser handoffs, not automatic
listing adapters. Your agent performs discovery and checks the current
original programme pages. See [opportunity modes](opportunities.md).
