"""Human-authored, evidence-linked investigation resolutions. No HTTP calls.

Resolutions persist separately from generated proposals so daily pipeline refreshes
cannot erase a human's proposed correction. Nothing here approves or applies.
"""
import hashlib
import json
from datetime import datetime, timezone

ALLOWED_FIELDS = {'name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'care_type', 'phone'}
TYPES = ('UPDATE_FIELDS', 'MARK_DUPLICATE', 'MARK_NEEDS_REVIEW', 'NO_CHANGE')


def initialize(con):
    con.execute('''CREATE TABLE IF NOT EXISTS investigation_resolutions (
      source_proposal_id TEXT PRIMARY KEY, resolution_id TEXT NOT NULL,
      resolution_type TEXT NOT NULL, author TEXT NOT NULL, reason TEXT NOT NULL,
      created_at TEXT NOT NULL, resolution_json TEXT NOT NULL,
      source_json TEXT NOT NULL
    )''')
    con.commit()


def list_resolutions(con):
    initialize(con)
    return [dict(r) for r in con.execute('SELECT * FROM investigation_resolutions ORDER BY created_at DESC')]


def resolution_proposals(con):
    return [json.loads(r['resolution_json']) for r in list_resolutions(con) if r['resolution_type']!='NO_CHANGE']


def excluded_sources(con):
    initialize(con)
    return {r[0] for r in con.execute('SELECT source_proposal_id FROM investigation_resolutions')}


def _candidate_ids(source):
    return {str(c.get('account_id')) for c in source.get('evidence',{}).get('candidates',[]) if c.get('account_id')}


def create_resolution(con, source, kind, reviewer, reason, accounts, target_id=None,
                      proposed_fields=None, survivor_id=None):
    if source.get('action')!='INVESTIGATE':
        raise ValueError('Only INVESTIGATE proposals can be resolved here')
    if kind not in TYPES: raise ValueError('Unknown resolution type')
    if not reviewer or not reviewer.strip() or not reason or len(reason.strip())<12:
        raise ValueError('Reviewer and meaningful evidence/reason (12+ characters) required')
    initialize(con)
    if con.execute('SELECT 1 FROM investigation_resolutions WHERE source_proposal_id=?', (source['proposal_id'],)).fetchone():
        raise ValueError('Investigation already resolved; do not silently replace the audit history')
    current={str(a['account_id']):a for a in accounts}
    allowed=_candidate_ids(source)
    target=None
    if kind!='NO_CHANGE':
        if not target_id or str(target_id) not in allowed or str(target_id) not in current:
            raise ValueError('Target must be one of the investigation candidate accounts in latest CRM snapshot')
        target=current[str(target_id)]
        if target.get('chow_current_account'):
            raise ValueError('CHOW-linked account requires separate ownership investigation')
    changes={}
    if kind=='UPDATE_FIELDS':
        proposed_fields=proposed_fields or {}
        if not proposed_fields or set(proposed_fields)-ALLOWED_FIELDS:
            raise ValueError('Select at least one allowed non-ownership field')
        for key,value in proposed_fields.items():
            value=str(value).strip()
            old=str(target.get(key) or '')
            if not value or value==old:continue
            changes[key]={'from':old,'to':value}
        if not changes:raise ValueError('No actual changes requested')
    elif kind=='MARK_DUPLICATE':
        if not survivor_id or str(survivor_id)==str(target_id) or str(survivor_id) not in allowed or str(survivor_id) not in current:
            raise ValueError('Survivor must be a different investigated candidate')
        survivor=current[str(survivor_id)]
        if target.get('duplicate_of_account') or survivor.get('duplicate_of_account'):
            raise ValueError('Existing duplicate link needs manual investigation')
        if target.get('parent_id')!=survivor.get('parent_id'):
            raise ValueError('Different parents could reflect CHOW; cannot mark duplicate directly')
        from normalizer import address, city, state, zipcode
        if not (address(target.get('billing_street')) and
                address(target.get('billing_street'))==address(survivor.get('billing_street')) and
                city(target.get('billing_city'))==city(survivor.get('billing_city')) and
                state(target.get('billing_state'))==state(survivor.get('billing_state')) and
                zipcode(target.get('billing_zip'))==zipcode(survivor.get('billing_zip'))):
            raise ValueError('Duplicate requires same normalized physical address')
        from crm_writer import money
        if money(target.get('lifetime_revenue'))!=0 or money(target.get('outstanding_ar'))!=0:
            raise ValueError('Losing account has financial history; manual billing review required')
        note=f'Confirmed duplicate of {survivor_id}. {reason.strip()}'
        changes={'status':{'from':target.get('status') or '', 'to':'Inactive'},
                 'duplicate_of_account':{'from':target.get('duplicate_of_account') or '', 'to':str(survivor_id)},
                 'note':{'from':target.get('note') or '', 'to':note}}
    elif kind=='MARK_NEEDS_REVIEW':
        if target.get('status')=='Inactive':raise ValueError('Do not change inactive accounts without further investigation')
        note=f'Ownership/identity investigation pending. {reason.strip()}'
        changes={'status':{'from':target.get('status') or '', 'to':'Needs Review'},
                 'note':{'from':target.get('note') or '', 'to':note}}
    base={'source_proposal_id':source['proposal_id'],'kind':kind,'target':target_id,
          'survivor':survivor_id,'changes':changes,'reason':reason.strip()}
    digest=hashlib.sha256(json.dumps(base,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    pid='resolution_'+digest
    p={'proposal_id':pid,'facility_name':source['facility_name'],
       'facility_key':source['facility_key'],'action':kind,'classification':'INVESTIGATION_RESOLVED',
       'account_id':str(target_id or ''),'proposed_changes':changes,
       'evidence':{**source.get('evidence',{}),'investigation_source_proposal_id':source['proposal_id'],
                   'resolution_reason':reason.strip(),'resolution_reviewer':reviewer.strip(),
                   'survivor_id':str(survivor_id or ''),
                   'target_snapshot':target},
       'reason':reason.strip(),'risk':'HIGH' if kind in ('MARK_DUPLICATE','MARK_NEEDS_REVIEW') else 'MEDIUM',
       'writeback_allowed':False}
    with con:
        con.execute('''INSERT INTO investigation_resolutions
          (source_proposal_id,resolution_id,resolution_type,author,reason,created_at,resolution_json,source_json)
          VALUES (?,?,?,?,?,?,?,?)''',
          (source['proposal_id'],pid,kind,reviewer.strip(),reason.strip(),
           datetime.now(timezone.utc).isoformat(),json.dumps(p,ensure_ascii=False),json.dumps(source,ensure_ascii=False)))
    return p
