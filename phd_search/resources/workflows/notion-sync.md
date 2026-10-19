# /notion-sync — authorised one-way pipeline view

Read `docs/integrations.md`. The local database stays authoritative. Use a real connected Notion tool only when the user requests publication/sync to a specific destination. A local export alone is not remote sync.

1. Resolve the target database/page and actual connected tool schema. Read current schema and rows within scope. Ask only for a missing destination or necessary authority; do not create a new external database or change access permissions on an inferred preference.
2. Generate `./roost export notion` and inspect the connector-neutral payload. It includes stable external IDs, titles, institution/country, status, original URL, deadline, funding, score/eligibility, last observation and document filenames. No CV, transcript, email body, profile, referee details or private document content is uploaded by default.
3. Map these values to the destination's actual property types. Upsert by external_id; avoid duplicate rows and preserve unrelated user-managed fields. Create a concise evidence-linked briefing only where requested. Null score/unknown funding must remain null/unknown, not zero/fully funded.
4. Complete the concrete local payload before seeking any missing final publication approval. When the user's request already authorises the specified write, carry it out within that scope. Never infer authority to share publicly or invite collaborators.
5. Record successful remote identifiers/dates in a local integration ledger. Report partial write failures and retry idempotently. Do not pull remote changes back into the candidate profile or tracker, and do not mark unexecuted writes successful.
