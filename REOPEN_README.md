# Phase 6 — Reopen Rejected Proposals

Only copy `app.py` and `review_store.py` into your existing project (replace both).
Optionally copy `tests/test_reopen.py` into `tests/` and run `python -m pytest -q`.

**Before replacement:** Stop Streamlit (`Ctrl+C`). Back up your existing `review.sqlite3` plus `app.py` and `review_store.py`. Keep `.env`, `data/`, `output/`, `review.sqlite3`, and all other files unchanged.

Restart: `python -m streamlit run app.py`.

In Streamlit: set Reviewer name → Decision history → Reopen a rejected proposal → select item → enter reason → Reopen Proposal → Pending. Reopening does not call the CRM API. The original rejection and reopen action remain in `review_events`; the active decision row is removed to allow re-review. The audit can be viewed in the Reopen audit trail expander.

Safety: only REJECTED proposals with `NOT_APPLIED` status, no applied time, and no stored writeback operation may be reopened. Already APPROVED/APPLIED records are untouched. If the original proposal is absent from current output, the UI prevents reopening until current matching results contain it again.

SQLite schema is upgraded lazily by creating a new `review_events` table; existing `decisions` and `operation_state` data are preserved.
