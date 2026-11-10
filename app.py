"""Local human review with explicit, separate approval and CRM application."""
import json
import csv
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from review_store import connect, load_pending, decide, history, get_decision, reopen_rejection, reopened_history
from payload_preview import preview
from crm_writer import CRMClient, apply_approved, SafetyError
from investigation_resolution import create_resolution, resolution_proposals, excluded_sources, list_resolutions, ALLOWED_FIELDS

load_dotenv()
st.set_page_config(page_title='Bellhaven CRM Review',layout='wide')
st.title('Bellhaven · CRM Reconciliation Review')
st.caption('Review evidence → Approve / Reject → separately Apply → GET read-back verification')
refresh_file = Path('output/refresh_status.json')
if refresh_file.exists():
    try:
        freshness = json.loads(refresh_file.read_text(encoding='utf-8'))
        st.caption(f"Last successful live-data refresh (UTC): {freshness.get('last_success_utc', 'unknown')} · CRM: {freshness.get('crm_count', '?')} · website: {freshness.get('website_count', '?')}")
    except (ValueError, OSError):
        st.warning('Refresh status is unreadable; verify source freshness before applying.')
else:
    st.info('No verified daily refresh yet. Proposals may be based on a saved snapshot; run python daily_runner.py before reviewing new changes.')
file=Path('output/proposals.json')
if not file.exists():
    st.error('Run python pipeline.py first to generate output/proposals.json')
    st.stop()
proposals=json.loads(file.read_text(encoding='utf-8'))
con=connect()
resolved_sources=excluded_sources(con)
manual_resolutions=resolution_proposals(con)
all_review_proposals=[p for p in proposals if p['proposal_id'] not in resolved_sources] + manual_resolutions
pending=load_pending(con,all_review_proposals)
logs=history(con)
cols=st.columns(3)
cols[0].metric('Pending',len(pending))
cols[1].metric('Decided',len(logs))
cols[2].metric('Applied',sum(x['application_status']=='APPLIED' for x in logs))
with st.sidebar:
    reviewer=st.text_input('Reviewer name')
    section=st.radio('View',['Pending review','Resolve investigations','Approved changes / Apply','Decision history'])

if section=='Decision history':
    st.dataframe(logs,use_container_width=True,hide_index=True)
    st.download_button('Download decision audit',json.dumps(logs,indent=2),'decisions.json')
    st.subheader('Reopen a rejected proposal')
    rejected = [r for r in logs if r['decision'] == 'REJECTED'
                and r['application_status'] == 'NOT_APPLIED']
    if not rejected:
        st.info('No eligible rejected proposals to reopen.')
    else:
        selected = st.selectbox('Rejected proposal', rejected,
            format_func=lambda r: f"{r['facility_name']} | {r['action']} | {r['proposal_id'][:8]}")
        st.write('Original rejection by:', selected['reviewer'])
        st.write('Original reason:', selected['reason'] or '(none recorded)')
        in_current = any(p['proposal_id'] == selected['proposal_id'] for p in proposals)
        if not in_current:
            st.warning('This proposal is not in the latest pipeline output; rerun the '
                       'pipeline and verify current evidence before reopening.')
        reopen_reason = st.text_area('Reason for reopening (required)',
                                     key='reopen_reason_'+selected['proposal_id'])
        if st.button('Reopen Proposal → Pending',
                     disabled=not reviewer.strip() or not reopen_reason.strip() or not in_current):
            try:
                reopen_rejection(con,selected['proposal_id'],reviewer,reopen_reason)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with st.expander('Reopen audit trail',expanded=False):
        st.dataframe(reopened_history(con),use_container_width=True,hide_index=True)

elif section=='Resolve investigations':
    st.subheader('Resolve investigation → reviewable CRM proposal')
    st.caption('Create a new proposal first. Another human approval and a separate Apply are still required before any API write.')
    candidates=[p for p in proposals if p['action']=='INVESTIGATE' and p['proposal_id'] not in resolved_sources]
    if not candidates:
        st.info('No unresolved investigations in current pipeline output.')
    else:
        source=st.selectbox('Investigation',candidates,
            format_func=lambda p:f"{p['facility_name']} | {p['proposal_id'][:8]}")
        st.write('**Why investigated:**',source.get('reason',''))
        st.write('**Official website:**',source.get('evidence',{}).get('website_url',''))
        st.write('**Website address:**',source.get('evidence',{}).get('website_address',''))
        with st.expander('Original evidence / ranked candidates',expanded=True):
            st.json(source.get('evidence',{}))
        crm_file=Path('data/crm_accounts.csv')
        if not crm_file.exists():
            st.error('Missing data/crm_accounts.csv; run python daily_runner.py')
            st.stop()
        with crm_file.open(encoding='utf-8-sig',newline='') as handle:
            accounts=list(csv.DictReader(handle))
        account_lookup={str(a['account_id']):a for a in accounts}
        ids=[str(c['account_id']) for c in source.get('evidence',{}).get('candidates',[])
             if str(c.get('account_id','')) in account_lookup]
        kind=st.selectbox('Resolution',[
            'UPDATE_FIELDS','MARK_DUPLICATE','MARK_NEEDS_REVIEW','NO_CHANGE'])
        target_id=''; survivor_id=''; fields={}
        if kind!='NO_CHANGE':
            if not ids:
                st.error('No candidate account in latest CRM snapshot. Investigate manually; cannot create a mutation.')
            else:
                target_id=st.selectbox('Target CRM account',ids,
                    format_func=lambda aid:f"{account_lookup[aid].get('name')} | {aid} | {account_lookup[aid].get('parent_name')}")
                st.dataframe([account_lookup[target_id]],use_container_width=True,hide_index=True)
                if kind=='UPDATE_FIELDS':
                    field_names=st.multiselect('Fields to correct (ownership not allowed)',sorted(ALLOWED_FIELDS))
                    for key in field_names:
                        fields[key]=st.text_input(f'New {key}',value=str(account_lookup[target_id].get(key) or ''),key=f'resolution_{source["proposal_id"]}_{target_id}_{key}')
                elif kind=='MARK_DUPLICATE':
                    alternatives=[i for i in ids if i!=target_id]
                    if alternatives:
                        survivor_id=st.selectbox('Surviving account', alternatives,
                            format_func=lambda aid:f"{account_lookup[aid].get('name')} | {aid}")
                    else:
                        st.error('At least two candidate accounts required for duplicate resolution.')
                    st.warning('Duplicate: requires matching physical address, same parent, and zero revenue AND zero AR on losing account. Live conditions checked again before Apply.')
                elif kind=='MARK_NEEDS_REVIEW':
                    st.warning('Changes status and note only. Do not use as a shortcut for unresolved ownership changes.')
        resolution_reason=st.text_area('Supporting evidence and reason (minimum 12 characters)',
                                       key='resolution_reason_'+source['proposal_id'])
        st.info('This button ONLY creates a new pending proposal, never writes to the CRM.')
        can_submit=bool(reviewer.strip()) and len(resolution_reason.strip())>=12 and (kind=='NO_CHANGE' or bool(ids))
        if st.button('Create resolution proposal / close investigation',disabled=not can_submit):
            try:
                result=create_resolution(con,source,kind,reviewer,resolution_reason,accounts,
                  target_id=target_id,proposed_fields=fields,survivor_id=survivor_id)
                st.success('Investigation resolution recorded. Review the new pending proposal before Approve/Apply.' if kind!='NO_CHANGE' else 'Investigation closed with no CRM change; reason retained.')
                st.rerun()
            except (ValueError,Exception) as exc:
                st.error(str(exc))
    with st.expander('Previously resolved investigations / audit',expanded=False):
        st.dataframe([{k:v for k,v in row.items() if k not in ('resolution_json','source_json')}
                      for row in list_resolutions(con)],use_container_width=True,hide_index=True)

elif section=='Pending review':
    if not pending:st.success('No pending proposals')
    else:
        p=st.selectbox('Proposal',pending,format_func=lambda p:f"{p['facility_name']} | {p['action']} | {p['proposal_id'][:8]}")
        st.subheader(p['facility_name'])
        st.write('**Action:**',p['action'],'· **Risk:**',p['risk'],'· **Classification:**',p['classification'])
        st.write('**Why:**',p['reason'])
        ev=p.get('evidence',{})
        st.write('**Official website:**',ev.get('website_url'))
        st.write('**Website address:**',ev.get('website_address'))
        st.write('**CRM candidate:**',ev.get('crm_name'),ev.get('crm_account_id'))
        if p['action'] in ('CHOW','REPARENT'):
            st.warning(f"Snapshot finance: revenue={ev.get('lifetime_revenue')} / AR={ev.get('outstanding_ar')}. Live values will be checked before apply.")
        if p['action']=='REVIEW_CREATE':
            st.warning('The candidate account ID is NOT a write target. Check all candidate records before approving a new account.')
        with st.expander('Matching evidence and candidate alternatives',expanded=True):st.json(ev)
        with st.expander('Exact API payload preview',expanded=True):st.json(preview(p))
        note=st.text_area('Review notes / rejection reason',key='review_'+p['proposal_id'])
        c1,c2=st.columns(2)
        if c1.button('Approve (save decision, NO API write)',disabled=not reviewer.strip() or p['action']=='INVESTIGATE',use_container_width=True):
            try:decide(con,p,'APPROVED',reviewer,note);st.rerun()
            except (ValueError,Exception) as exc:st.error(str(exc))
        if c2.button('Reject',disabled=not reviewer.strip(),use_container_width=True):
            try:decide(con,p,'REJECTED',reviewer,note);st.rerun()
            except ValueError as exc:st.error(str(exc))
else:
    approved=[r for r in logs if r['decision']=='APPROVED']
    if not approved:st.info('No approved changes yet')
    else:
        chosen=st.selectbox('Approved proposal',approved,format_func=lambda r:f"{r['facility_name']} | {r['action']} | {r['application_status']}")
        row=get_decision(con,chosen['proposal_id'])
        p=json.loads(row['proposal_snapshot'])
        st.subheader(p['facility_name'])
        st.write('**Application status:**',row['application_status'])
        if row.get('application_error'):st.error(row['application_error'])
        with st.expander('Approved evidence',expanded=False):st.json(p['evidence'])
        st.write('**Exact planned API calls (ID placeholder resolved after POST):**')
        st.json(preview(p))
        st.caption('Payload shape is inferred from CRM fields; the OpenAPI docs omit requestBody. No writes are performed merely by opening this page.')
        st.warning('Applying will modify your personal CRM sandbox. Live account fields and CHOW conditions will be checked. Create operations may require manual reconciliation if a network error occurs.')
        confirm=st.checkbox('I reviewed this exact proposal and authorize these CRM API changes',key='confirm_'+p['proposal_id'])
        typed=st.text_input('Type APPLY to confirm',key='type_'+p['proposal_id'])
        disabled=not confirm or typed!='APPLY' or row['application_status'] not in ('NOT_APPLIED','BLOCKED')
        if st.button('Apply approved change to CRM',type='primary',disabled=disabled):
            try:
                client=CRMClient()
                result=apply_approved(con,client,p['proposal_id'])
                st.success(f"Verified CRM change: {result}")
                st.rerun()
            except Exception as exc:
                st.error(f'Change was not confirmed as applied: {exc}. See status before retrying.')
