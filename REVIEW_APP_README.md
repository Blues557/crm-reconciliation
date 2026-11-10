# Phase 3: Schema Audit & Human Review (READ-ONLY WRITEBACK)

## What is implemented
- A **GET-only** `schema_audit.py` searches common OpenAPI URLs, extracts POST / PATCH / PUT account paths and request body fields, and writes `output/schema_audit.json`.
- `payload_preview.py` translates business proposals to *illustrative* account payloads, never makes requests. `UPDATE_FIELDS` strips `{from,to}` wrappers; `CHOW` previews two distinct steps.
- `app.py` Streamlit Review UI shows proposed changes, financial data, candidate alternatives, evidence links, approval/rejection, history and schema audit.
- `review_store.py` SQLite decisions; on reruns, semantically identical decided proposals are hidden. Approval is `NOT_APPLIED` until a separate verified writeback implementation exists.

## Run in the same project folder as your previous pipeline

```powershell
python -m pip install -r requirements.txt
python pipeline.py
python schema_audit.py
python -m streamlit run app.py
python -m pytest -q
```

**Never commit** `.env`, `review.sqlite3`, or `data/` to a public GitHub repo.

## Actual schema confirmation outstanding
This environment cannot reach the authenticated OpenAPI document. Do not claim schema compatibility based on the proposed field names alone. Check `output/schema_audit.json` and the interactive docs: https://analyst-assessment-production.up.railway.app/api/docs

Verify:
1. PATCH path (account identifier argument), HTTP method, accepted request fields and response shape.
2. POST path, required fields (including optional care_type, phone, status) and returned new account ID.
3. Whether nullable `parent_id`, `chow_current_account`, `duplicate_of_account` and `note` are supported by PATCH.
4. Live account GET for precondition check before mutations; billing revenue/AR must be refreshed before reparenting.
5. CHOW: create new account + persist its ID, then only set old account's `chow_current_account`; recover safely from partial failure.
6. Before creating account, search live CRM for an existing facility and CHOW successor.
7. Mark actual application state as `APPLIED` only after HTTP success AND read-after-write verification.

## Important limitations
- **No CRM writeback yet**. Clicking Approve stores a review decision, not a CRM mutation.
- `INVESTIGATE` cannot be approved as a mutation. Investigate and generate a new actionable proposal.
- Some `REVIEW_CREATE` proposals contain a low-ranked CRM candidate ID; it is not a target account.
- Current proposal fingerprints include the proposed source values. A true source change generates a new fingerprint and therefore a new proposal. Decisions for the same semantic revision are not repeated.
- Back up `review.sqlite3` across restarts; it is intentionally excluded from git.
- JSON snapshot and CSV files contain CRM business data and must not be published.
