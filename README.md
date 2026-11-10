<<<<<<< HEAD
# Bellhaven CRM Reconciliation — Phase 1: Read-only data collection

This is **phase 1 only**, not the finished assignment. It does **not** write to the CRM or implement matching/review yet.

## Quick start

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
cp .env.example .env    # Windows: copy .env.example .env
# edit .env and insert personal API token (never commit .env)
python collect.py
```

## Outputs (under `data/`; intentionally gitignored)

- `crm_accounts_raw.json`, `crm_accounts.csv`: CRM accounts retrieved via GET.
- `crm_first_response_shape.json`: keys found in first API response, to validate pagination.
- `website_locations_raw.json`, `website_locations.csv`: discovered website facility detail pages.
- `website_listing_diagnostics.json`: listing discovery counts by page.
- `profile.json`: dataset size, field names, parent distribution, missing structured website addresses.

## Important limitations / manual validation

- CRM pagination uses a defensive generic parser. Verify `crm_count` against the read-only CRM browser (~120 expected). If count differs, inspect the first-response shape and adjust page parameters.
- HTML structure is not yet verified. The scraper prefers JSON-LD structured addresses or `<address>`; it **flags** incomplete structured addresses. Do not assume all fields are correct without inspection.
- Care offerings are text keyword candidates, *not confirmed* service tags. Review detail-page markup before using them as strong matching evidence.
- Directory pagination may vary; confirm count and inspect pages manually. Homepage-linked facilities are also checked.
- API token belongs only in `.env`. Never paste it in issues, logs or screenshots.
- No account modifications happen in this phase. Next phases: schema validation, normalization, entity matching, CHOW policy, review app, approval-only writeback, and idempotency checks.
=======
# crm-reconciliation
Automated CRM ownership reconciliation with entity matching and human-in-the-loop review
>>>>>>> origin/main
