"""Read-only daily refresh: live CRM + website -> validated snapshots -> proposals.

This module NEVER calls CRM POST/PATCH. Explicit human approval and Apply are
handled only by app.py/crm_writer.py. Historical SQLite decisions are preserved.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import collect
from pipeline import DEFAULT_PARENT, read_csv, run
from review_store import connect, load_pending

CRM_MIN = 100
WEB_MIN = 30


def validate_snapshot(crm, website, *, previous_crm=None, previous_website=None):
    """Fail closed on empty/truncated or malformed scraping results."""
    if len(crm) < CRM_MIN:
        raise ValueError(f'CRM snapshot suspiciously small: {len(crm)} < {CRM_MIN}')
    if len(website) < WEB_MIN:
        raise ValueError(f'Website snapshot suspiciously small: {len(website)} < {WEB_MIN}')
    for label, current, prior in [('CRM', len(crm), previous_crm), ('website', len(website), previous_website)]:
        if prior and current < prior * .8:
            raise ValueError(f'{label} count dropped by more than 20% ({prior} -> {current}); investigate before replacing snapshot')
    ids = [str(a.get('account_id') or '') for a in crm]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('CRM account IDs missing or duplicated')
    if any(not (a.get('name') and a.get('parent_id') is not None) for a in crm):
        raise ValueError('CRM name/parent data malformed')
    keys = [str(w.get('source_url') or '') for w in website]
    if any(not x for x in keys) or len(set(keys)) != len(keys):
        raise ValueError('Website URLs missing or duplicated')
    required = ('name', 'address', 'city', 'state', 'zip')
    for w in website:
        if any(not str(w.get(field) or '').strip() for field in required) or w.get('needs_address_review'):
            raise ValueError(f'Website address incomplete: {w.get("source_url", "unknown")}')


def run_daily(*, data_dir='data', output_dir='output', db_path='review.sqlite3', parent_id=DEFAULT_PARENT):
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / '.daily_runner.lock'
    # Prevent overlapping scheduled runs. If a process crashes, remove stale
    # lock only after confirming that no other daily_runner is executing.
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'w') as lock_file:
            lock_file.write(f'PID {os.getpid()}\n')
        with tempfile.TemporaryDirectory(prefix='bellhaven-refresh-') as temp:
            staging = Path(temp)
            staged_data = staging / 'data'
            staged_output = staging / 'output'
            staged_data.mkdir()
            staged_output.mkdir()
            old_out = collect.OUT
            try:
                # The existing collector writes only to collect.OUT; direct
                # its files to a temporary directory until validation passes.
                collect.OUT = staged_data
                crm = collect.collect_crm()
                if not crm:
                    raise ValueError('CRM collection returned no data; token/API unavailable')
                website = collect.collect_website()
                collect.profile(crm, website)
            finally:
                collect.OUT = old_out
            prev_crm = read_csv(data_dir / 'crm_accounts.csv') if (data_dir / 'crm_accounts.csv').exists() else None
            prev_web = read_csv(data_dir / 'website_locations.csv') if (data_dir / 'website_locations.csv').exists() else None
            validate_snapshot(crm, website, previous_crm=len(prev_crm) if prev_crm else None,
                              previous_website=len(prev_web) if prev_web else None)
            results, proposals, stale = run(staged_data/'crm_accounts.csv', staged_data/'website_locations.csv', staged_output, parent_id)
            # The static snapshot may include a previously applied change. The
            # new pipeline always evaluates fresh CRM API data, not old CSVs.
            con = connect(db_path)
            try:
                pending = load_pending(con, proposals)
                decided = con.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]
            finally:
                con.close()
            metadata = {
                'last_success_utc': datetime.now(timezone.utc).isoformat(),
                'crm_count': len(crm), 'website_count': len(website),
                'generated_proposals': len(proposals), 'pending_after_decisions': len(pending),
                'stored_decisions': decided, 'stale_review_count': len(stale),
                'read_only': True,
                'note': 'CRM changes can only occur via explicit human approval and Apply in Streamlit'
            }
            (staged_output/'refresh_status.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            # All network operations and validation finish BEFORE existing
            # snapshot/proposal files are replaced. Decisions DB is untouched.
            for src_dir, target_dir in ((staged_data, data_dir), (staged_output, output_dir)):
                for file in src_dir.iterdir():
                    if file.is_file():
                        os.replace(file, target_dir/file.name)
            print(json.dumps(metadata, indent=2))
            return metadata
    finally:
        lock_path.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description='Refresh live data; NEVER writes CRM')
    ap.add_argument('--data-dir', default='data')
    ap.add_argument('--out', default='output')
    ap.add_argument('--db', default='review.sqlite3')
    ap.add_argument('--parent-id', default=DEFAULT_PARENT)
    args = ap.parse_args()
    run_daily(data_dir=args.data_dir, output_dir=args.out, db_path=args.db, parent_id=args.parent_id)


if __name__ == '__main__':
    main()
