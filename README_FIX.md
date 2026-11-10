# Matching tests fix (deterministic fixtures)

## Copy into existing repository

- Replace `tests/test_matching.py` with the supplied `tests/test_matching.py`.
- Add `tests/fixtures/scenarios.py` (new file).
- Keep existing `matcher.py`, `classifier.py`, `normalizer.py`, `pipeline.py`, `data/`, `output/`, `.env`, and `review.sqlite3` unchanged.

## Run

```powershell
python -m pytest -q
python daily_runner.py
python -m pytest -q
```

The tests no longer load mutable `data/crm_accounts.csv` or `data/website_locations.csv`, so their expectations remain constant after the real CRM is corrected. The synthetic scenarios cover cross-state name collisions, CHOW, direct reparenting, already-fixed parents, duplicates, major rebrands, ZIP correction, and deterministic proposal IDs.

Local verification: 10/10 tests in this replacement matching-test module passed with the accompanying project code. This does not guarantee all other tests in your local checkout will pass.

## Important caveat

The matching engine currently labels *all* strongly similar co-located accounts `MULTIPLE_ACCOUNTS`, including legitimate historical CHOW pairs. That is a separate production matching improvement, not a test fixture problem. Do not rewrite CRM data to satisfy the tests, and do not change this regression test to approve all co-located accounts.
