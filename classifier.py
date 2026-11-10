"""Business classification after entity matching (read-only)."""
import normalizer as n


def classify(web, resolution, by_id, bellhaven_id):
    status=resolution['match_status']; top=resolution['top']
    if status=='MULTIPLE_ACCOUNTS':
        return {'classification':'MULTIPLE_ACCOUNTS_REVIEW','action':'INVESTIGATE','reason':'Multiple same-location accounts; determine duplicates vs ownership history before any modification'}
    if status=='AMBIGUOUS': return {'classification':'AMBIGUOUS','action':'INVESTIGATE','reason':resolution['ambiguity_reason']}
    if status=='NO_MATCH': return {'classification':'MISSING_ACCOUNT_CANDIDATE','action':'REVIEW_CREATE','reason':'No sufficiently supported CRM match; verify before creating'}
    account=by_id[top['account_id']]
    if account.get('duplicate_of_account') or account.get('chow_current_account'):
        return {'classification':'LINKED_ACCOUNT_REVIEW','action':'INVESTIGATE','reason':'Existing duplicate/CHOW link must be resolved before new proposals'}
    if top['parent_id']!=bellhaven_id:
        needs_chow=n.money(account.get('lifetime_revenue'))>0 and n.money(account.get('outstanding_ar'))>0
        return {'classification':'WRONG_PARENT','action':'CHOW' if needs_chow else 'REPARENT','reason':'Official website lists facility as Bellhaven; CRM currently has different parent. '+('Revenue and outstanding AR both positive; preserve old account.' if needs_chow else 'CHOW financial threshold not met.')}
    changes={}
    for field,wfield,crmfield,fn in [
        ('name','name','name',n.name),('billing_street','address','billing_street',n.address),
        ('billing_city','city','billing_city',n.city),('billing_state','state','billing_state',n.state),('billing_zip','zip','billing_zip',n.zipcode)]:
        if fn(web.get(wfield)) != fn(account.get(crmfield)) and web.get(wfield):
            changes[field]={'from':account.get(crmfield,''),'to':web[wfield]}
    # A full renaming of an account with low name similarity is a possible facility replacement,
    # not automatically an outdated label. Require explicit identity confirmation.
    if 'name' in changes and top['name_score'] < 60:
        return {'classification':'MAJOR_REBRAND_REVIEW','action':'INVESTIGATE','reason':'Street matches, but business name is materially different; verify license/ownership identity before renaming','suggested_fields':changes}
    # Never silently overwrite an unverified physical address (especially a PO Box).
    if not top['location_strong']:
        return {'classification':'FIELD_REVIEW','action':'INVESTIGATE','reason':'Identity accepted provisionally but physical address not verified','suggested_fields':changes}
    if changes:return {'classification':'FIELD_MISMATCH','action':'UPDATE_FIELDS','reason':'Matched Bellhaven account has mismatched public-facing fields','suggested_fields':changes}
    return {'classification':'MATCHED','action':'NO_ACTION','reason':'Identity, parent, and core fields consistent'}


def stale_accounts(web_resolutions, accounts, bellhaven_id):
    # Any account associated with a location, even if ambiguous, is excluded from an automatic stale conclusion.
    associated=set()
    for item in web_resolutions:
        r=item['resolution']
        for c in r['candidates']:
            if c['location_strong'] and c['score']>=70 or (c['city_match'] and c['name_score']>=90): associated.add(c['account_id'])
    return [{'account_id':a['account_id'],'name':a['name'],'classification':'STALE_ACCOUNT_REVIEW','action':'INVESTIGATE','reason':'Account under Bellhaven but no supported website link; absence is NOT proof of divestiture'} for a in accounts if a.get('parent_id')==bellhaven_id and a['account_id'] not in associated]
