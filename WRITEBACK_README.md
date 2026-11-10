# Phase 4: Approval-gated CRM Writer

## Setup

From your existing project folder, copy `app.py`, `crm_writer.py`, and `review_store.py` from this release (keep your `.env`, `data`, `output` and `review.sqlite3`).

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python pipeline.py
python -m streamlit run app.py
```

The `.env` file needs `CRM_API_TOKEN=...`. Never commit `.env`, account exports, or `review.sqlite3` to public GitHub.

## Explicit review/write workflow

1. **Pending review:** inspect official website evidence and ranked candidates. Approve or reject. Approval only saves a decision to SQLite.
2. **Approved changes / Apply:** select an approved proposal, inspect the exact HTTP payload, tick the authorization box, type `APPLY`, click **Apply approved change to CRM**.
3. The writer GETs the CRM record, compares proposed `from` fields, enforces live financial CHOW rules, submits only approved POST/PATCH operations, then GETs the account(s) to verify results.
4. `APPLIED` means verified. `BLOCKED` means validation failed before writing or readback could not be verified. `UNKNOWN_WRITE` means the server may have written despite a request error; **do not retry blindly**.

## API compatibility caveat

The sandbox OpenAPI document exposes POST/PATCH endpoints but **does not specify `requestBody`**. The code uses observed GET field names for request bodies and defers to runtime validation. Do not claim endpoint write-field compatibility is proven until a human-approved low-risk PATCH has been applied and GET-verified. This package has not performed any network mutation.

## Special safeguards

- `INVESTIGATE` is non-executable. No delete/merge API calls.
- `REVIEW_CREATE` ranked `account_id` is deliberately ignored as a target; creation checks for same-address live accounts first.
- `REPARENT` blocks if both lifetime revenue and outstanding AR are positive.
- `CHOW` creates a new account and changes **only** `chow_current_account` on the historical account. The old parent and billing fields are preserved.
- POST success + follow-up failure persists the created ID for recovery. If POST outcome itself is unknown, status is `UNKNOWN_WRITE` and the system prohibits retry until manually reconciled.
- SQLite approval is bound to a frozen proposal snapshot. A new scrape does not mutate previously approved payloads.

## Limitations to address before production

This is an assessment sandbox implementation, not a transactionally atomic writer. In particular, a two-call CHOW is not atomic and still needs a documented manual recovery procedure. SQLite is local and must be backed up; concurrent reviewers should be serialized. Current API docs don't guarantee field schemas or concurrency controls. Test with an approved, low-risk UPDATE_FIELDS first.
