"""Build evidence-rich, READ-ONLY proposals and stable content fingerprints."""
import hashlib,json
import normalizer as n


def proposal(web,resolution,decision,by_id,bellhaven_id):
    action=decision['action']
    if action=='NO_ACTION':return None
    top=resolution['top']; account=by_id.get(top['account_id']) if top else None
    proposed={}
    if action=='UPDATE_FIELDS': proposed=decision.get('suggested_fields',{})
    elif action=='REPARENT': proposed={'parent_id':{'from':account['parent_id'],'to':bellhaven_id}}
    elif action=='CHOW': proposed={'new_account':{'name':web['name'],'parent_id':bellhaven_id,'address':web['address'],'city':web['city'],'state':web['state'],'zip':web['zip']},'old_account':{'account_id':account['account_id'],'only_mutation':'chow_current_account -> new account id'}}
    elif action=='REVIEW_CREATE': proposed={'new_account_candidate':{'name':web['name'],'parent_id':bellhaven_id,'address':web['address'],'city':web['city'],'state':web['state'],'zip':web['zip']}}
    evidence={'website_url':web.get('source_url',''),'website_name':web['name'],'website_address':', '.join(filter(None,[web.get('address'),web.get('city'),web.get('state'),n.zipcode(web.get('zip'))])),'crm_account_id':account.get('account_id') if account else None,'crm_parent_id':account.get('parent_id') if account else None,'crm_name':account.get('name') if account else None,'lifetime_revenue':account.get('lifetime_revenue') if account else None,'outstanding_ar':account.get('outstanding_ar') if account else None,'candidates':resolution['candidates'],'matching_status':resolution['match_status'],'explanation':decision['reason']}
    identity={'facility_key':n.facility_key(web),'action':action,'account_id':account['account_id'] if account else None,'proposed':proposed}
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    return {'proposal_id':fingerprint,'status':'PENDING','facility_name':web['name'],'facility_key':n.facility_key(web),'action':action,'classification':decision['classification'],'account_id':account['account_id'] if account else '', 'proposed_changes':proposed,'evidence':evidence,'reason':decision['reason'],'risk':'HIGH' if action in ('CHOW','INVESTIGATE','REVIEW_CREATE') else 'MEDIUM','writeback_allowed':False}
