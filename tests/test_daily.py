import csv
import json
import pytest

import daily_runner
from review_store import connect, decide, load_pending


def test_validation_blocks_missing_addresses():
    crm=[{'account_id':str(i), 'name':'A', 'parent_id':''} for i in range(101)]
    web=[{'name':'A','address':'1 St','city':'City','state':'OH','zip':'12345','source_url':f'https://example.com/{i}','needs_address_review':False} for i in range(31)]
    daily_runner.validate_snapshot(crm,web)
    web[0]['address']=''
    with pytest.raises(ValueError, match='address incomplete'):
        daily_runner.validate_snapshot(crm,web)


def test_validation_blocks_truncated_refresh():
    crm=[{'account_id':str(i), 'name':'A', 'parent_id':''} for i in range(101)]
    web=[{'name':'A','address':'1 St','city':'City','state':'OH','zip':'12345','source_url':f'https://example.com/{i}','needs_address_review':False} for i in range(31)]
    with pytest.raises(ValueError, match='dropped'):
        daily_runner.validate_snapshot(crm,web,previous_crm=150)


def test_decisions_survive_data_refresh(tmp_path, monkeypatch):
    import collect
    import pandas as pd
    data=tmp_path/'data';output=tmp_path/'output';data.mkdir();output.mkdir()
    db=tmp_path/'decisions.sqlite3'
    p={'proposal_id':'x', 'facility_key':'ABC', 'facility_name':'Demo', 'action':'UPDATE_FIELDS', 'account_id':'id1',
       'proposed_changes':{'name':{'from':'a','to':'b'}}}
    con=connect(db);decide(con,p,'REJECTED','human');con.close()
    crm=[{'account_id':str(i), 'name':'Account', 'parent_id':''} for i in range(101)]
    website=[{'name':'Demo','address':'1 Main St','city':'City','state':'OH','zip':'12345','source_url':f'https://example.com/{i}','needs_address_review':False} for i in range(31)]
    def fake_crm():
        pd.DataFrame(crm).to_csv(collect.OUT/'crm_accounts.csv',index=False)
        return crm
    def fake_web():
        pd.DataFrame(website).to_csv(collect.OUT/'website_locations.csv',index=False)
        return website
    def fake_profile(c,w): pass
    def fake_run(c,w,o,parent):
        o.mkdir(exist_ok=True)
        (o/'proposals.json').write_text(json.dumps([p]))
        return [],[p],[]
    monkeypatch.setattr(collect,'collect_crm',fake_crm)
    monkeypatch.setattr(collect,'collect_website',fake_web)
    monkeypatch.setattr(collect,'profile',fake_profile)
    monkeypatch.setattr(daily_runner,'run',fake_run)
    result=daily_runner.run_daily(data_dir=data,output_dir=output,db_path=db)
    assert result['pending_after_decisions']==0
    assert result['stored_decisions']==1
    assert (data/'crm_accounts.csv').exists()
    assert not (output/'.daily_runner.lock').exists()


def test_failed_refresh_keeps_previous_files(tmp_path,monkeypatch):
    import collect
    data=tmp_path/'data';out=tmp_path/'output';data.mkdir();out.mkdir()
    (data/'crm_accounts.csv').write_text('OLD CRM')
    (out/'proposals.json').write_text('OLD PROPOSALS')
    monkeypatch.setattr(collect,'collect_crm',lambda: [])
    with pytest.raises(ValueError, match='no data'):
        daily_runner.run_daily(data_dir=data,output_dir=out,db_path=tmp_path/'review.sqlite3')
    assert (data/'crm_accounts.csv').read_text()=='OLD CRM'
    assert (out/'proposals.json').read_text()=='OLD PROPOSALS'
    assert not (out/'.daily_runner.lock').exists()
