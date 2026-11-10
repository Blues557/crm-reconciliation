import pytest
from review_store import connect, load_pending, decide
from investigation_resolution import create_resolution, resolution_proposals, excluded_sources
from crm_writer import apply_approved, SafetyError
from payload_preview import preview
class FakeClient:
    def __init__(self): self.records={};self.writes=[]
    def get_account(self,aid): return dict(self.records[aid])
    def patch(self,aid,body):
        self.writes.append(('PATCH',aid,body));self.records[aid].update(body)
    def list_accounts(self): return list(self.records.values())


def account(aid, name, street='10 Main St', parent='parent', revenue='0', ar='0'):
    return {'account_id':aid,'name':name,'billing_street':street,
            'billing_city':'Town','billing_state':'OH','billing_zip':'44444',
            'parent_id':parent,'lifetime_revenue':revenue,'outstanding_ar':ar,
            'status':'Active','note':'','duplicate_of_account':'','chow_current_account':''}


def source():
    return {'proposal_id':'invest1','action':'INVESTIGATE','facility_name':'Bellhaven X',
        'facility_key':'OH|44444|10 main st|town','evidence':{
          'candidates':[{'account_id':'a'},{'account_id':'b'}],
          'website_url':'https://example.com'}}


def test_manual_field_update_requires_review_and_apply(tmp_path):
    con=connect(tmp_path/'a.sqlite3'); a=account('a','Old');b=account('b','Other')
    p=create_resolution(con,source(),'UPDATE_FIELDS','reviewer','Official website confirms new branding',[a,b],
        target_id='a',proposed_fields={'name':'Bellhaven X'})
    assert p['action']=='UPDATE_FIELDS'
    assert p['proposed_changes']['name']=={'from':'Old','to':'Bellhaven X'}
    assert preview(p)[0]['body']=={'name':'Bellhaven X'}
    assert excluded_sources(con)=={'invest1'}
    assert [r['proposal_id'] for r in load_pending(con,resolution_proposals(con))]==[p['proposal_id']]
    crm=FakeClient();crm.records={'a':a,'b':b};crm.writes=[]
    with pytest.raises(SafetyError):apply_approved(con,crm,p['proposal_id'])
    decide(con,p,'APPROVED','reviewer','Evidence independently reviewed')
    assert apply_approved(con,crm,p['proposal_id'])['status']=='APPLIED'
    assert crm.records['a']['name']=='Bellhaven X'
    assert crm.writes==[('PATCH','a',{'name':'Bellhaven X'})]


def test_duplicate_restrictions_and_live_financial_guard(tmp_path):
    con=connect(tmp_path/'b.sqlite3');a=account('a','Duplicate');b=account('b','Survivor')
    p=create_resolution(con,source(),'MARK_DUPLICATE','reviewer','Same licensed facility and same identity',[a,b],
        target_id='a',survivor_id='b')
    assert preview(p)[0]['body']['duplicate_of_account']=='b'
    decide(con,p,'APPROVED','reviewer')
    crm=FakeClient();crm.records={'a':dict(a,lifetime_revenue='50'),'b':b};crm.writes=[]
    with pytest.raises(SafetyError,match='financial history'):apply_approved(con,crm,p['proposal_id'])
    assert not crm.writes


def test_duplicate_parent_mismatch_blocked(tmp_path):
    con=connect(tmp_path/'c.sqlite3');a=account('a','A');b=account('b','B',parent='different')
    with pytest.raises(ValueError,match='Different parents'):
        create_resolution(con,source(),'MARK_DUPLICATE','reviewer','These have matching facilities',[a,b],
           target_id='a',survivor_id='b')


def test_no_change_closes_investigation_without_api(tmp_path):
    con=connect(tmp_path/'d.sqlite3')
    p=create_resolution(con,source(),'NO_CHANGE','reviewer','Insufficient evidence to change account',[])
    assert p['action']=='NO_CHANGE'
    assert resolution_proposals(con)==[]
    assert excluded_sources(con)=={'invest1'}
    with pytest.raises(ValueError,match='already resolved'):
        create_resolution(con,source(),'NO_CHANGE','reviewer','Insufficient evidence to change account',[])


def test_target_must_be_candidate(tmp_path):
    con=connect(tmp_path/'e.sqlite3')
    with pytest.raises(ValueError,match='candidate'):
        create_resolution(con,source(),'UPDATE_FIELDS','reviewer','Evidence supports new account name',
            [account('x','Unknown')],target_id='x',proposed_fields={'name':'New'})
