import json
import pytest
from review_store import connect,decide,load_pending,fingerprint,history
from schema_audit import inspect

def sample(action='UPDATE_FIELDS'):
 return {'proposal_id':'abc123','facility_name':'Example','facility_key':'OH|44236|1 main|town','action':action,'account_id':'acct1','proposed_changes':{'name':{'from':'A','to':'B'}}}

def test_decision_persists_and_suppresses_rerun(tmp_path):
 db=tmp_path/'review.db';p=sample();c=connect(db)
 assert len(load_pending(c,[p]))==1
 decide(c,p,'REJECTED','reviewer','reason')
 assert load_pending(c,[p])==[]
 c.close(); c=connect(db)
 assert load_pending(c,[p])==[]
 assert history(c)[0]['application_status']=='NOT_APPLIED'
 with pytest.raises(ValueError):decide(c,p,'APPROVED','reviewer')

def test_investigate_cannot_be_approved(tmp_path):
 c=connect(tmp_path/'review.db')
 with pytest.raises(ValueError):decide(c,sample('INVESTIGATE'),'APPROVED','reviewer')

def test_schema_fields():
 spec = {
  'openapi': '3.0.0',
  'paths': {'/api/v1/accounts/{id}': {'patch': {
    'requestBody': {'content': {'application/json': {
      'schema': {'$ref': '#/components/schemas/AccountPatch'}
    }}}
  }}},
  'components': {'schemas': {'AccountPatch': {'properties': {
    'parent_id': {'type': 'string'},
    'chow_current_account': {'type': 'string'}
  }}}}
 }

 report=inspect(spec)
 assert len(report['account_mutations'])==1
 assert 'chow_current_account' in report['account_mutations'][0]['fields']

def test_create_fingerprint_ignores_candidate_id():
 p=sample('REVIEW_CREATE');q={**p,'account_id':'some-other-candidate'}
 assert fingerprint(p)==fingerprint(q)

def test_payload_preview_chow_only_links_old():
 from payload_preview import preview
 p=sample('CHOW')
 p['proposed_changes']={'new_account':{'name':'Bellhaven X','parent_id':'bell','address':'1 Main','city':'A','state':'OH','zip':'44444'},'old_account':{'account_id':'old123','only_mutation':'chow_current_account -> new account id'}}
 ops=preview(p)
 assert len(ops)==2
 assert ops[0]['body']['billing_street']=='1 Main'
 assert ops[1]['body']=={'chow_current_account':'<ID FROM CREATE RESPONSE>'}
 assert 'parent_id' not in ops[1]['body']

def test_payload_preview_update_flattens_diffs():
 from payload_preview import preview
 p=sample()
 assert preview(p)[0]['body']=={'name':'B'}
