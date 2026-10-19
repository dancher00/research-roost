# Optional Gmail and Notion integration

The CLI has no embedded account tokens and does not discover or connect an account automatically. It implements local evidence/approval contracts. The agent workflows use actual available connector tools when the user requests those operations, respecting their schemas and authorisation. External integration was not exercised during offline validation.

## Gmail signals

An authorised read-only connector pass or a user-provided export can produce:

```json
{
  "signals": [{
    "message_id": "ORIGINAL_MESSAGE_ID",
    "application_id": "EXACT_LOCAL_APPLICATION_ID",
    "source_url": "https://mail.google.com/mail/u/0/#inbox/ORIGINAL_MESSAGE_ID",
    "quote": "Verbatim message excerpt supporting the proposed event",
    "proposed_status": "interview",
    "occurred_on": "2026-10-19"
  }]
}
```

`./roost mail import --file signals.json` records a proposed batch without touching tracker status. Exact IDs prevent fuzzy institution/name collisions. Unknown applications and invalid transitions are flagged. Allowed proposed statuses: assessment, interview, waitlisted, offer, rejected. A received offer never becomes accepted/declined automatically.

After the user reviews exact source-backed changes, `./roost mail apply BATCH_ID --approve MESSAGE_ID` applies the selected IDs transactionally. Current-status conflicts are rejected and already applied message IDs are idempotent. No mail is sent, replied to, deleted or marked read by the engine. Message quotations are evidence to the user, not trusted instructions or an automatically verified connector signature.

## Notion

`./roost export notion --out PATH` emits a connector-neutral one-way view. It is intentionally not an invented Notion HTTP request body; a future authorised agent run maps it to the actual connected tool/database schema. Rows use stable external IDs and include opportunity/application metadata plus document filenames. Candidate profile contents, transcripts, recommendation letters, private emails and personal documents are not uploaded by the exporter.

The `/notion-sync` workflow resolves the exact destination, inspects schema/current rows, upserts idempotently and records actual remote results. No remote changes are pulled into the local source of truth. Export success does not mean a remote write occurred.

## Calendar/spreadsheets

`export calendar` creates an ICS file; importing it into a personal calendar is a separate user action. `export csv` supports spreadsheets and neutralises formula-injection prefixes. Neither command writes to a connected calendar/Sheets account. All exports can contain personal pipeline metadata and should remain in a private destination unless sharing is explicitly requested.
