"""Deterministic matching regression tests. Never read refreshed CRM snapshots.

Fixtures are synthetic, so daily_runner.py cannot change expected outcomes.
"""
import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

import normalizer as n
from matcher import resolve
from classifier import classify
from pipeline import run
import sys
from pathlib import Path
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURE_DIR))
from scenarios import BELLHAVEN, account, facility, scenario


def evaluate(case):
    website, accounts, _, _ = scenario(case)
    result = resolve(website, accounts)
    by_id = {a["account_id"]: a for a in accounts}
    decision = classify(website, result, by_id, BELLHAVEN)
    return result, decision


def test_normalization():
    assert n.address("1120 West Main Street") == n.address("1120 W Main St")
    assert n.zipcode("45662.0") == "45662"
    assert n.care("Short-Term Rehabilitation & Nursing") == {"nursing_rehab"}
    assert n.money("12,400") > 0


def test_cross_state_same_name_not_a_match():
    result, decision = evaluate("cross_state")
    assert result["match_status"] == "NO_MATCH"
    assert result["top"] is None
    assert decision["action"] == "REVIEW_CREATE"


def test_chow_with_revenue_and_outstanding_ar():
    result, decision = evaluate("chow")
    assert result["match_status"] == "CONFIDENT_MATCH"
    assert decision["action"] == "CHOW"


def test_no_chow_when_ar_is_zero():
    _, decision = evaluate("chow_ar_zero")
    assert decision["action"] == "REPARENT"


def test_reparent_when_wrong_parent_without_ar():
    _, decision = evaluate("reparent")
    assert decision["action"] == "REPARENT"


def test_reparent_no_longer_proposed_after_parent_fixed():
    _, decision = evaluate("reparent_fixed")
    assert decision["action"] == "NO_ACTION"


def test_same_location_two_accounts_requires_investigation():
    result, decision = evaluate("duplicate_address")
    assert result["match_status"] == "MULTIPLE_ACCOUNTS"
    assert decision["action"] == "INVESTIGATE"


def test_major_rename_requires_investigation():
    result, decision = evaluate("major_rename")
    assert result["match_status"] in ("CONFIDENT_MATCH", "REVIEW_MATCH")
    assert decision["classification"] == "MAJOR_REBRAND_REVIEW"
    assert decision["action"] == "INVESTIGATE"


def test_zip_discrepancy_proposes_field_update():
    _, decision = evaluate("wrong_zip")
    assert decision["action"] == "UPDATE_FIELDS"
    assert decision["suggested_fields"]["billing_zip"]["to"] == "45662"


def _save_csv(path, rows):
    columns = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_repeatable_proposal_fingerprints(tmp_path):
    # Run the full pipeline twice on *fixed synthetic* inputs, not mutable data/*.csv.
    website, accounts, _, _ = scenario("reparent")
    crm_path = tmp_path / "crm.csv"
    web_path = tmp_path / "website.csv"
    _save_csv(crm_path, accounts)
    _save_csv(web_path, [website])
    _, first, _ = run(crm_path, web_path, tmp_path / "first", parent_id=BELLHAVEN)
    _, second, _ = run(crm_path, web_path, tmp_path / "second", parent_id=BELLHAVEN)
    assert len(first) == len(second) == 1
    assert first[0]["proposal_id"] == second[0]["proposal_id"]
