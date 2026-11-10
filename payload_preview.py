"""Pure proposal -> potential CRM payload conversion. NO HTTP REQUESTS.
These mappings require confirmation against the real API schema before use.
"""

FIELD_MAP={'address':'billing_street','city':'billing_city','state':'billing_state','zip':'billing_zip'}

def account_fields(src):
    return {FIELD_MAP.get(k,k):v for k,v in src.items() if k not in ('account_id','only_mutation')}

def preview(proposal):
    action=proposal['action']; changes=proposal.get('proposed_changes',{})
    if action in ('UPDATE_FIELDS','MARK_DUPLICATE','MARK_NEEDS_REVIEW'):
        return [{'operation':'UPDATE_ACCOUNT','account_id':proposal['account_id'],'body':{k:v['to'] for k,v in changes.items()}}]
    if action=='REPARENT':
        return [{'operation':'UPDATE_ACCOUNT','account_id':proposal['account_id'],'body':{'parent_id':changes['parent_id']['to']}}]
    if action=='CHOW':
        return [
            {'operation':'CREATE_ACCOUNT','body':account_fields(changes['new_account'])},
            {'operation':'UPDATE_OLD_ACCOUNT','account_id':changes['old_account']['account_id'],'body':{'chow_current_account':'<ID FROM CREATE RESPONSE>'}}
        ]
    if action=='REVIEW_CREATE':
        return [{'operation':'CREATE_ACCOUNT','body':account_fields(changes['new_account_candidate'])}]
    return []
