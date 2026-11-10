"""Approval-gated CRM writes. Importing this module never performs HTTP requests.

Mutations are only called from apply_approved() after SQLite approval and explicit
UI confirmation. APIs are imperfectly documented, so every successful operation
is re-read; uncertain creates never automatically retry.
"""
import os
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
import requests

from payload_preview import preview
from review_store import get_decision, mark_application, get_operation_state, save_operation_state

DEFAULT_BASE = 'https://analyst-assessment-production.up.railway.app/api/v1'
ALLOWED_UPDATE = {'name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'care_type', 'phone', 'parent_id', 'status', 'note', 'chow_current_account', 'duplicate_of_account'}
ALLOWED_CREATE = {'name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'care_type', 'phone', 'parent_id', 'status', 'note'}
REQUIRED_CREATE = {'name', 'billing_street', 'billing_city', 'billing_state', 'billing_zip', 'parent_id'}

class SafetyError(Exception):
    pass

class CRMClient:
    def __init__(self, token=None, base=None, session=None):
        self.base = (base or os.getenv('CRM_API_BASE') or DEFAULT_BASE).rstrip('/')
        self.token = token or os.getenv('CRM_API_TOKEN')
        if not self.token:
            raise SafetyError('CRM_API_TOKEN is missing')
        parsed = urlparse(self.base)
        if parsed.scheme != 'https' or parsed.hostname != 'analyst-assessment-production.up.railway.app' or parsed.path != '/api/v1':
            raise SafetyError('Unexpected CRM API URL; this writer is restricted to the assessment sandbox')
        self.s = session or requests.Session()
        self.headers = {'Authorization': f'Bearer {self.token}', 'Accept': 'application/json'}

    def request(self, method, path, body=None, params=None):
        if method not in ('GET','POST','PATCH'):
            raise SafetyError('Unsupported HTTP method')
        headers=dict(self.headers)
        if body is not None: headers['Content-Type']='application/json'
        response=self.s.request(method, self.base+path, headers=headers, json=body, params=params, timeout=20)
        response.raise_for_status()
        try:return response.json()
        except ValueError:raise SafetyError(f'{method} {path} returned non-JSON result; verify CRM manually')

    def get_account(self, account_id):
        result=self.request('GET',f'/accounts/{account_id}')
        if isinstance(result,dict):
            for k in ('account','data'):
                if isinstance(result.get(k),dict):return result[k]
        if not isinstance(result,dict) or not result.get('account_id'):
            raise SafetyError('GET account response missing account_id')
        return result

    def list_accounts(self):
        found=[]; seen=set()
        for page in range(1,31):
            data=self.request('GET','/accounts',params={'page':page,'limit':100})
            if isinstance(data,list): rows=data
            elif isinstance(data,dict):
                rows=next((data[k] for k in ('accounts','results','items','data','records') if isinstance(data.get(k),list)),None)
                if rows is None:raise SafetyError('Cannot identify account list in API response')
            else:raise SafetyError('Unexpected list accounts response')
            new=[r for r in rows if r.get('account_id') and r['account_id'] not in seen]
            for r in new:seen.add(r['account_id'])
            found.extend(new)
            if len(rows)<100 or not new:return found
        raise SafetyError('CRM pagination exceeded safety limit')

    def patch(self, account_id, body):
        validate_body(body,False)
        return self.request('PATCH',f'/accounts/{account_id}',body=body)

    def create(self, body):
        validate_body(body,True)
        return self.request('POST','/accounts',body=body)


def validate_body(body, creating):
    if not isinstance(body,dict) or not body:raise SafetyError('Empty or invalid API request body')
    allowed=ALLOWED_CREATE if creating else ALLOWED_UPDATE
    unknown=set(body)-allowed
    if unknown:raise SafetyError(f'Disallowed write fields: {sorted(unknown)}')
    if creating and (REQUIRED_CREATE-set(body)):
        raise SafetyError(f'Missing required creation fields: {sorted(REQUIRED_CREATE-set(body))}')
    if any(v is None or isinstance(v,(dict,list)) for v in body.values()):
        raise SafetyError('Body has null or nested values')


def money(v):
    try:return Decimal(str(v or '0').replace(',','').replace('$',''))
    except InvalidOperation:raise SafetyError('Financial field is missing or invalid')


def _equal(a,b):
    return str(a if a is not None else '') == str(b if b is not None else '')


def _assert_same_values(account, values):
    for k,v in values.items():
        if not _equal(account.get(k),v):raise SafetyError(f'Stale CRM value for {k}: expected {v!r}; found {account.get(k)!r}. Re-run matching before applying')


def _assert_fields(account,body):
    for k,v in body.items():
        if not _equal(account.get(k),v):raise SafetyError(f'CRM read-back mismatch: {k}')


def _same_facility(a, body):
    # Strict collision check intentionally errs on the side of requiring investigation.
    def norm(s):return ' '.join(str(s or '').lower().replace('.','').split())
    return (norm(a.get('billing_street'))==norm(body.get('billing_street')) and
            norm(a.get('billing_city'))==norm(body.get('billing_city')) and
            norm(a.get('billing_state'))==norm(body.get('billing_state')) and
            norm(a.get('billing_zip'))==norm(body.get('billing_zip')))


def _assert_no_collision(client, body, exclude_ids=()):
    matches=[a for a in client.list_accounts() if a.get('account_id') not in exclude_ids and _same_facility(a,body) and not a.get('duplicate_of_account')]
    if matches:raise SafetyError(f'Potential existing account at same address: {[a["account_id"] for a in matches]}. Investigate rather than create another')


def _assert_approved(con, proposal_id):
    row=get_decision(con,proposal_id)
    if row is None or row['decision']!='APPROVED':raise SafetyError('A durable human APPROVED decision is required')
    if row['application_status']=='APPLIED':raise SafetyError('Already applied; no duplicate write allowed')
    if row['application_status'] in ('APPLYING','UNKNOWN_WRITE'):
        raise SafetyError('Previous write status is uncertain; reconcile manually before retrying')
    return row


def apply_approved(con, client, proposal_id):
    """Called only by explicit 'Apply approved change' UI interaction, NEVER by pipeline.

    In multi-request CHOW, persist new account ID immediately so a later retry
    can ONLY update the old link rather than recreate a facility.
    """
    import json
    row=_assert_approved(con,proposal_id)
    p=json.loads(row['proposal_snapshot'])
    action=p['action']
    if action not in ('UPDATE_FIELDS','REPARENT','CHOW','REVIEW_CREATE','MARK_DUPLICATE','MARK_NEEDS_REVIEW'):
        raise SafetyError(f'Action {action} is not executable')
    ops=preview(p)
    if not ops:raise SafetyError('No write operations')
    # Never trust an unvalidated preview.
    for op in ops:validate_body(op['body'],op['operation']=='CREATE_ACCOUNT' and '<ID' not in str(op['body']))
    try:
        if action in ('UPDATE_FIELDS','REPARENT','MARK_DUPLICATE','MARK_NEEDS_REVIEW'):
            account=client.get_account(p['account_id'])
            if account['account_id']!=p['account_id']:raise SafetyError('Account ID mismatch')
            changes=p['proposed_changes']
            _assert_same_values(account,{k:v['from'] for k,v in changes.items()})
            if action=='REPARENT':
                if account.get('chow_current_account') or account.get('duplicate_of_account'):
                    raise SafetyError('Existing CHOW or duplicate link requires investigation')
                if money(account.get('lifetime_revenue'))>0 and money(account.get('outstanding_ar'))>0:
                    raise SafetyError('CHOW threshold now met; direct reparent forbidden')
            if action in ('MARK_DUPLICATE','MARK_NEEDS_REVIEW'):
                # Additional live-data safety checks; notes/status alone are not proof.
                if account.get('chow_current_account'):
                    raise SafetyError('Existing CHOW link; investigation required')
                if action=='MARK_DUPLICATE':
                    if money(account.get('lifetime_revenue')) != 0 or money(account.get('outstanding_ar')) != 0:
                        raise SafetyError('Losing duplicate has financial history; billing review required')
                    survivor_id=changes['duplicate_of_account']['to']
                    survivor=client.get_account(survivor_id)
                    if survivor.get('account_id') != survivor_id or survivor.get('duplicate_of_account'):
                        raise SafetyError('Invalid surviving account')
                    if survivor.get('parent_id') != account.get('parent_id'):
                        raise SafetyError('Different parents; possible ownership change')
                    from normalizer import address, city, state, zipcode
                    if not (address(account.get('billing_street')) and
                            address(account.get('billing_street'))==address(survivor.get('billing_street')) and
                            city(account.get('billing_city'))==city(survivor.get('billing_city')) and
                            state(account.get('billing_state'))==state(survivor.get('billing_state')) and
                            zipcode(account.get('billing_zip'))==zipcode(survivor.get('billing_zip'))):
                        raise SafetyError('Surviving and losing accounts do not share physical address')
                if action=='MARK_NEEDS_REVIEW' and account.get('status')=='Inactive':
                    raise SafetyError('Inactive account cannot be marked Needs Review automatically')
            body=ops[0]['body']
            mark_application(con,proposal_id,'APPLYING')
            try:client.patch(p['account_id'],body)
            except Exception:
                mark_application(con,proposal_id,'UNKNOWN_WRITE','PATCH failed/uncertain; re-read CRM before retry')
                raise
            latest=client.get_account(p['account_id'])
            _assert_fields(latest,body)
            mark_application(con,proposal_id,'APPLIED')
            return {'status':'APPLIED','account_id':p['account_id']}
        if action in ('CHOW','REVIEW_CREATE'):
            create_body=ops[0]['body']
            old_id=p['proposed_changes']['old_account']['account_id'] if action=='CHOW' else None
            state=get_operation_state(con,proposal_id)
            new_id=state.get('created_account_id')
            if action=='REVIEW_CREATE' and p.get('account_id'):
                # account_id in REVIEW_CREATE is a ranked search candidate, not target.
                pass
            if action=='CHOW':
                old=client.get_account(old_id)
                if old['account_id']!=old_id:raise SafetyError('Old account ID mismatch')
                if old.get('parent_id')!=p['evidence']['crm_parent_id']:
                    raise SafetyError('Old parent changed since proposal was generated')
                if money(old.get('lifetime_revenue'))<=0 or money(old.get('outstanding_ar'))<=0:
                    raise SafetyError('CHOW threshold no longer met; manual re-evaluation required')
                if old.get('chow_current_account'):
                    if new_id and str(old['chow_current_account'])==new_id:
                        mark_application(con,proposal_id,'APPLIED');return {'status':'APPLIED','account_id':new_id}
                    raise SafetyError('Old account already has a CHOW link')
                if old.get('duplicate_of_account'):raise SafetyError('Old account already duplicate-linked')
            if not new_id:
                _assert_no_collision(client,create_body,exclude_ids=([old_id] if old_id else []))
                mark_application(con,proposal_id,'APPLYING')
                # If POST times out after server creates an account, do not retry blindly.
                try:created=client.create(create_body)
                except Exception:
                    mark_application(con,proposal_id,'UNKNOWN_WRITE','POST outcome uncertain. Find created account before retry')
                    raise
                new_id=(created.get('account_id') or (created.get('account') or {}).get('account_id') or (created.get('data') or {}).get('account_id')) if isinstance(created,dict) else None
                if not new_id:
                    mark_application(con,proposal_id,'UNKNOWN_WRITE','POST response lacked account_id; reconcile manually')
                    raise SafetyError('POST returned no account_id; do not automatically retry')
                save_operation_state(con,proposal_id,{'created_account_id':new_id})
            latest=client.get_account(new_id)
            _assert_fields(latest,create_body)
            if action=='CHOW':
                # This is the ONLY mutation allowed to the old billed account.
                mark_application(con,proposal_id,'APPLYING')
                try:client.patch(old_id,{'chow_current_account':new_id})
                except Exception:
                    mark_application(con,proposal_id,'UNKNOWN_WRITE','Old-account link PATCH uncertain; reconcile before retry')
                    raise
                old_after=client.get_account(old_id)
                _assert_fields(old_after,{'chow_current_account':new_id, 'parent_id':p['evidence']['crm_parent_id']})
            mark_application(con,proposal_id,'APPLIED')
            return {'status':'APPLIED','account_id':new_id}
    except SafetyError as e:
        current=get_decision(con,proposal_id)
        if current['application_status'] not in ('UNKNOWN_WRITE','APPLIED'):
            mark_application(con,proposal_id,'BLOCKED',str(e))
        raise
