import copy
import json
import pytest
from review_store import connect, decide, get_decision
from crm_writer import apply_approved, SafetyError, validate_body


def proposal(action='UPDATE_FIELDS'):
    changes=({'name':{'from':'Old','to':'New'}} if action=='UPDATE_FIELDS' else
             {'parent_id':{'from':'old_parent','to':'bellhaven'}} if action=='REPARENT' else
             {'new_account':{'name':'Bellhaven X','parent_id':'bellhaven','address':'1 Main','city':'Town','state':'OH','zip':'44444'},'old_account':{'account_id':'old1'}})
    return {'proposal_id':'id_'+action,'facility_key':'OH|44444|1 main|town','facility_name':'Bellhaven X','action':action,'account_id':'old1','proposed_changes':changes,'evidence':{'crm_parent_id':'old_parent'}}

class FakeClient:
    def __init__(self,old=None, fail_create=False):
        self.old=old or {'account_id':'old1','name':'Old','parent_id':'old_parent','lifetime_revenue':100,'outstanding_ar':0,'chow_current_account':None,'duplicate_of_account':None}
        self.records={'old1':copy.deepcopy(self.old)};self.writes=[];self.fail_create=fail_create
    def get_account(self,id):return copy.deepcopy(self.records[id])
    def list_accounts(self):return list(self.records.values())
    def patch(self,id,body):
        self.writes.append(('PATCH',id,body));self.records[id].update(body);return self.records[id]
    def create(self,body):
        self.writes.append(('POST',body))
        if self.fail_create:raise RuntimeError('post timeout')
        a={'account_id':'new1',**body};self.records['new1']=a;return a


def approve(con,p):decide(con,p,'APPROVED','human')

def test_update_only_after_approval(tmp_path):
    c=connect(tmp_path/'review.db');p=proposal();crm=FakeClient()
    with pytest.raises(SafetyError):apply_approved(c,crm,p['proposal_id'])
    approve(c,p)
    assert apply_approved(c,crm,p['proposal_id'])['status']=='APPLIED'
    assert crm.writes==[('PATCH','old1',{'name':'New'})]
    with pytest.raises(SafetyError):apply_approved(c,crm,p['proposal_id'])
    # decisions can still be made after adding application tracking columns
    q=proposal('REPARENT');decide(c,q,'REJECTED','other')

def test_reparent_financial_guard(tmp_path):
    c=connect(tmp_path/'r.db');p=proposal('REPARENT');approve(c,p)
    crm=FakeClient({'account_id':'old1','parent_id':'old_parent','lifetime_revenue':'100','outstanding_ar':'200','chow_current_account':None})
    with pytest.raises(SafetyError,match='CHOW threshold'):apply_approved(c,crm,p['proposal_id'])
    assert crm.writes==[]

def test_chow_preserves_old_and_links(tmp_path):
    c=connect(tmp_path/'r.db');p=proposal('CHOW');approve(c,p)
    crm=FakeClient({'account_id':'old1','name':'Historical','parent_id':'old_parent','lifetime_revenue':100,'outstanding_ar':25,'chow_current_account':None,'duplicate_of_account':None})
    res=apply_approved(c,crm,p['proposal_id'])
    assert res['account_id']=='new1'
    assert crm.records['old1']['parent_id']=='old_parent'
    assert crm.records['old1']['name']=='Historical'
    assert crm.records['old1']['chow_current_account']=='new1'
    assert crm.writes[-1]==('PATCH','old1',{'chow_current_account':'new1'})

def test_unknown_post_not_retried(tmp_path):
    c=connect(tmp_path/'r.db');p=proposal('CHOW');approve(c,p)
    crm=FakeClient({'account_id':'old1','parent_id':'old_parent','lifetime_revenue':100,'outstanding_ar':25,'chow_current_account':None},fail_create=True)
    with pytest.raises(RuntimeError):apply_approved(c,crm,p['proposal_id'])
    assert get_decision(c,p['proposal_id'])['application_status']=='UNKNOWN_WRITE'
    with pytest.raises(SafetyError):apply_approved(c,crm,p['proposal_id'])
    assert len(crm.writes)==1

def test_disallowed_fields():
    with pytest.raises(SafetyError):validate_body({'lifetime_revenue':12},False)
