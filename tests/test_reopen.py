import json
import pytest
from review_store import (connect, decide, load_pending, reopen_rejection,
                          reopened_history, history, mark_application,
                          save_operation_state)


def proposal(pid='p1'):
    return {'proposal_id':pid, 'facility_key':'OH|44236|1 main|town',
            'facility_name':'Example', 'action':'UPDATE_FIELDS', 'account_id':'a1',
            'proposed_changes':{'name':{'from':'Old','to':'New'}}}


def test_reopen_rejected_returns_to_pending_and_preserves_audit(tmp_path):
    c=connect(tmp_path/'test.db'); p=proposal()
    decide(c,p,'REJECTED','reviewerA','Incorrect candidate')
    assert len(load_pending(c,[p])) == 0
    reopen_rejection(c,p['proposal_id'],'reviewerB','Verified official address')
    assert len(load_pending(c,[p])) == 1
    assert history(c) == []
    events=reopened_history(c)
    assert len(events)==1
    assert events[0]['previous_reviewer']=='reviewerA'
    assert events[0]['previous_reason']=='Incorrect candidate'
    assert events[0]['change_reason']=='Verified official address'
    decide(c,p,'APPROVED','reviewerB')
    assert len(load_pending(c,[p])) == 0
    c.close()
    c=connect(tmp_path/'test.db')
    assert len(reopened_history(c))==1
    assert history(c)[0]['decision']=='APPROVED'


def test_approved_and_applied_are_never_reopened(tmp_path):
    c=connect(tmp_path/'test.db'); p=proposal()
    decide(c,p,'APPROVED','reviewer')
    with pytest.raises(ValueError,match='Only rejected'):
        reopen_rejection(c,'p1','admin','Reason')
    assert history(c)[0]['decision']=='APPROVED'


def test_reopen_rejects_missing_reason_and_reviewer(tmp_path):
    c=connect(tmp_path/'test.db'); p=proposal();decide(c,p,'REJECTED','reviewer')
    with pytest.raises(ValueError,match='Reviewer'):
        reopen_rejection(c,'p1','','Reason')
    with pytest.raises(ValueError,match='reason'):
        reopen_rejection(c,'p1','admin','')
    assert len(load_pending(c,[p]))==0


def test_reopen_blocks_mutation_state(tmp_path):
    c=connect(tmp_path/'test.db');p=proposal();decide(c,p,'REJECTED','reviewer')
    save_operation_state(c,'p1',{'created_account_id':'something'})
    with pytest.raises(ValueError,match='operation history'):
        reopen_rejection(c,'p1','admin','Reason')
    assert history(c)[0]['decision']=='REJECTED'


def test_reopen_blocks_non_default_application_state(tmp_path):
    c=connect(tmp_path/'test.db');p=proposal();decide(c,p,'REJECTED','reviewer')
    mark_application(c,'p1','BLOCKED','Manually blocked')
    with pytest.raises(ValueError,match='writeback state'):
        reopen_rejection(c,'p1','admin','Reason')
    assert len(reopened_history(c))==0
