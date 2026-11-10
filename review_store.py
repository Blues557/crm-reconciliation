"""Persistent human decisions; approval NEVER implies successful CRM application."""
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def connect(db_path='review.sqlite3'):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS decisions (
      proposal_id TEXT PRIMARY KEY,
      fingerprint TEXT NOT NULL,
      action TEXT NOT NULL,
      facility_name TEXT NOT NULL,
      decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
      reviewer TEXT NOT NULL,
      reason TEXT NOT NULL DEFAULT '',
      decided_at TEXT NOT NULL,
      proposal_snapshot TEXT NOT NULL,
      application_status TEXT NOT NULL DEFAULT 'NOT_APPLIED'
    )''')
    con.commit()
    return con


def fingerprint(p):
    """Stable semantic identity; exclude volatile evidence and candidate rankings."""
    import hashlib
    payload = {'facility_key':p['facility_key'], 'action':p['action'],
               'account_id': '' if p['action']=='REVIEW_CREATE' else p.get('account_id',''),
               'proposed_changes':p.get('proposed_changes',{})}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def load_pending(con, proposals):
    approved = {r['fingerprint']: r for r in con.execute('SELECT * FROM decisions')}
    return [p for p in proposals if fingerprint(p) not in approved]


def decide(con,p,decision,reviewer,reason=''):
    if decision not in ('APPROVED','REJECTED'):
        raise ValueError('Decision must be APPROVED or REJECTED')
    if not reviewer or not reviewer.strip():
        raise ValueError('Reviewer is required')
    if p['action']=='INVESTIGATE' and decision=='APPROVED':
        raise ValueError('Investigation proposals cannot be approved as a CRM mutation')
    fp=fingerprint(p)
    with con:
        existing=con.execute('SELECT decision FROM decisions WHERE fingerprint=?',(fp,)).fetchone()
        if existing:
            raise ValueError('This proposal was already decided')
        # A human decision is preserved in the DB, never silently replaced.
        con.execute('''INSERT INTO decisions (proposal_id,fingerprint,action,facility_name,decision,reviewer,reason,decided_at,proposal_snapshot,application_status) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (p['proposal_id'],fp,p['action'],p['facility_name'],decision,
                     reviewer.strip(),reason.strip(),utcnow(),json.dumps(p,ensure_ascii=False),'NOT_APPLIED'))


def history(con):
    return [dict(r) for r in con.execute('SELECT proposal_id,action,facility_name,decision,reviewer,reason,decided_at,application_status FROM decisions ORDER BY decided_at DESC')]

# Writeback tracking is added non-destructively to existing Phase 3 databases.
def ensure_writeback_tables(con):
    con.execute('''CREATE TABLE IF NOT EXISTS operation_state (
        proposal_id TEXT PRIMARY KEY,
        state_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL
    )''')
    cols={r['name'] for r in con.execute('PRAGMA table_info(decisions)')}
    if 'application_error' not in cols:
        con.execute("ALTER TABLE decisions ADD COLUMN application_error TEXT NOT NULL DEFAULT ''")
    if 'applied_at' not in cols:
        con.execute('ALTER TABLE decisions ADD COLUMN applied_at TEXT')
    con.commit()


def get_decision(con,proposal_id):
    ensure_writeback_tables(con)
    r=con.execute('SELECT * FROM decisions WHERE proposal_id=?',(proposal_id,)).fetchone()
    return dict(r) if r else None


def mark_application(con,proposal_id,status,error=''):
    ensure_writeback_tables(con)
    if status not in ('NOT_APPLIED','APPLYING','APPLIED','BLOCKED','UNKNOWN_WRITE'):
        raise ValueError('Invalid application status')
    with con:
        con.execute('UPDATE decisions SET application_status=?, application_error=?, applied_at=? WHERE proposal_id=?',
                    (status,error,utcnow() if status=='APPLIED' else None,proposal_id))


def get_operation_state(con,proposal_id):
    ensure_writeback_tables(con)
    r=con.execute('SELECT state_json FROM operation_state WHERE proposal_id=?',(proposal_id,)).fetchone()
    return json.loads(r['state_json']) if r else {}


def save_operation_state(con,proposal_id,state):
    ensure_writeback_tables(con)
    with con:
        con.execute('''INSERT INTO operation_state(proposal_id,state_json,updated_at)
                       VALUES (?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET
                       state_json=excluded.state_json, updated_at=excluded.updated_at''',
                    (proposal_id,json.dumps(state,ensure_ascii=False),utcnow()))

# Reopening removes the active suppression record but retains the prior rejection
# and the reopening rationale in an append-only audit table.
def ensure_review_events(con):
    con.execute("""CREATE TABLE IF NOT EXISTS review_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposal_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        event_type TEXT NOT NULL CHECK(event_type IN ('REOPEN_REJECTION')),
        previous_decision TEXT NOT NULL, previous_reviewer TEXT NOT NULL,
        previous_reason TEXT NOT NULL, previous_decided_at TEXT NOT NULL,
        previous_snapshot TEXT NOT NULL, changed_by TEXT NOT NULL,
        change_reason TEXT NOT NULL, changed_at TEXT NOT NULL
    )""")
    con.commit()


def reopened_history(con):
    ensure_review_events(con)
    return [dict(r) for r in con.execute('SELECT * FROM review_events ORDER BY event_id DESC')]


def reopen_rejection(con, proposal_id, reviewer, reason):
    if not reviewer or not reviewer.strip():
        raise ValueError('Reviewer is required')
    if not reason or not reason.strip():
        raise ValueError('Reopen reason is required for the audit trail')
    ensure_writeback_tables(con)
    ensure_review_events(con)
    with con:
        row = con.execute('SELECT * FROM decisions WHERE proposal_id=?', (proposal_id,)).fetchone()
        if row is None:
            raise ValueError('Decision not found')
        if row['decision'] != 'REJECTED':
            raise ValueError('Only rejected proposals can be reopened')
        if row['application_status'] != 'NOT_APPLIED' or row['applied_at'] is not None:
            raise ValueError('Proposal has writeback state; reopening is blocked')
        if con.execute('SELECT 1 FROM operation_state WHERE proposal_id=?', (proposal_id,)).fetchone():
            raise ValueError('Proposal has operation history; reopening is blocked')
        con.execute('''INSERT INTO review_events (
            proposal_id,fingerprint,event_type,previous_decision,previous_reviewer,
            previous_reason,previous_decided_at,previous_snapshot,
            changed_by,change_reason,changed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (row['proposal_id'],row['fingerprint'],'REOPEN_REJECTION',row['decision'],
             row['reviewer'],row['reason'],row['decided_at'],row['proposal_snapshot'],
             reviewer.strip(),reason.strip(),utcnow()))
        con.execute('DELETE FROM decisions WHERE proposal_id=? AND decision=?',
                    (proposal_id,'REJECTED'))
    return {'proposal_id':proposal_id,'status':'PENDING'}
