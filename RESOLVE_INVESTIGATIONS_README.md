# Phase 7 — Resolve investigations

This patch extends the existing Bellhaven Streamlit app. It does **not** modify the CRM during proposal creation.

## Install

Stop Streamlit (`Ctrl+C`). Make a safe copy of your existing `review.sqlite3` and original `app.py`, `crm_writer.py`, `payload_preview.py`. Copy the patch files into your existing project, preserving the folder structure:

- `app.py` — **replace** existing file. Based on Phase 6 (Reopen) plus Phase 5 (daily refresh).
- `crm_writer.py` — **replace** existing file.
- `payload_preview.py` — **replace** existing file.
- `investigation_resolution.py` — **new** file.
- `tests/test_investigation_resolution.py` — **new** file.

**Do not replace** `.env`, `data/`, `output/`, `review.sqlite3`, or other Python modules.

The new `investigation_resolutions` SQLite table is created automatically. Existing `decisions`, `operation_state`, and `review_events` tables are preserved.

Run:

```powershell
python -m pytest -q
python daily_runner.py
python -m streamlit run app.py
```

## Workflow

1. In the left sidebar enter Reviewer name; select **Resolve investigations**.
2. Choose the source INVESTIGATE record, review its website evidence and CRM candidates.
3. Choose a resolution:
   - **UPDATE_FIELDS:** select a candidate account, choose safe non-ownership fields, and provide corrected values.
   - **MARK_DUPLICATE:** choose losing and surviving candidate accounts. Only same-parent, same-address accounts with zero revenue and zero AR on the loser are eligible. Both accounts are rechecked at Apply time.
   - **MARK_NEEDS_REVIEW:** change the selected account's `status` to `Needs Review` and set an evidence-based `note`.
   - **NO_CHANGE:** close this investigation with a reason and no CRM write.
4. Provide at least 12 characters of rationale and select **Create resolution proposal / close investigation**. No API call is made.
5. For a change, go to **Pending review** and independently Approve/Reject the newly generated proposal.
6. Go to **Approved changes / Apply**, inspect the exact request body, type APPLY, and only then trigger the API write. GET read-back verifies the outcome.

Every resolution persists in SQLite and the original source proposal is suppressed from Pending; the human-authored proposal remains in Pending until decided, including after daily refreshes. `NO_CHANGE` stores its reason but produces no change request.

## Safety limitations

- The API's OpenAPI schema omits the request body. Request payload shapes were inferred from known CRM fields and must be verified in the sandbox.
- `MARK_DUPLICATE` is intentionally conservative and blocks any losing account with positive lifetime revenue or non-zero outstanding AR, different parents, different normalized physical addresses, or existing CHOW links.
- `MARK_NEEDS_REVIEW` should not be applied to operationally sound facilities based only on a missing listing.
- Do not use investigation resolution for ownership moves: all re-parenting must go through the separate CHOW-aware proposal logic.
- A completed resolution cannot be edited in place (to preserve the audit trail). If it was wrong, do not approve/apply; further review should produce an explicitly tracked replacement workflow.
- SQLite must be backed up and persisted; a daily GitHub Actions runner does not preserve local SQLite by default.
- Local test result for this patch: **33 passed**, using mocked CRM for writer safety tests. No live CRM mutations were made during patch development.
