"""Candidate retrieval, evidence scoring, and ambiguity detection. No CRM writes."""
from dataclasses import dataclass, asdict
from rapidfuzz import fuzz
import normalizer as n

@dataclass
class Candidate:
    account_id: str
    crm_name: str
    parent_id: str
    parent_name: str
    score: float
    address_score: float
    name_score: float
    city_match: bool
    state_match: bool
    zip_match: bool
    care_score: float | None
    location_strong: bool
    evidence: list[str]


def score(web, crm):
    st_match=n.state(web.get('state')) == n.state(crm.get('billing_state'))
    if not st_match or not n.state(web.get('state')): return None
    name_score=fuzz.token_sort_ratio(n.name(web.get('name')),n.name(crm.get('name')))
    address_score=fuzz.ratio(n.address(web.get('address')),n.address(crm.get('billing_street')))
    cm=n.city(web.get('city')) == n.city(crm.get('billing_city'))
    zm=bool(n.zipcode(web.get('zip'))) and n.zipcode(web.get('zip'))==n.zipcode(crm.get('billing_zip'))
    wc=n.care(web.get('care_offerings'));cc=n.care(crm.get('care_type'))
    care_score=100*len(wc&cc)/len(wc|cc) if wc and cc else None
    # If care is unavailable, renormalize the weights rather than silently treating unknown as mismatch.
    weights=[(.4,address_score),(.25,name_score),(.15,100 if zm else 0),(.10,100 if cm else 0)]
    if care_score is not None: weights.append((.10,care_score))
    total=sum(w*v for w,v in weights)/sum(w for w,_ in weights)
    physical=cm and ((zm and address_score>=83) or address_score>=94)
    # A PO box is a mailing address, not a physical location match.
    if n.is_po_box(crm.get('billing_street')) or n.is_po_box(web.get('address')): physical=False
    ev=[]
    if cm:ev.append('City matches')
    if zm:ev.append('ZIP matches')
    if address_score>=90:ev.append('Street address near-exact')
    if name_score>=90:ev.append('Name near-exact')
    if not cm:ev.append('City differs')
    if not zm:ev.append('ZIP differs')
    if n.is_po_box(crm.get('billing_street')):ev.append('CRM address is PO Box; physical address unverified')
    return Candidate(str(crm.get('account_id','')),str(crm.get('name','')),str(crm.get('parent_id','')),str(crm.get('parent_name','')),round(total,2),round(address_score,2),round(name_score,2),cm,True,zm,None if care_score is None else round(care_score,2),physical,ev)


def rank(web, accounts, limit=6):
    candidates=[candidate for crm in accounts if (candidate:=score(web,crm)) is not None]
    candidates.sort(key=lambda c:(c.location_strong,c.score,c.name_score),reverse=True)
    return candidates[:limit]


def resolve(web, accounts):
    candidates=rank(web,accounts)
    primary=candidates[0] if candidates else None
    if not primary: return {'match_status':'NO_MATCH','top':None,'candidates':[],'ambiguity_reason':'No account in the same state'}
    # Strong physical evidence, or exact-ish name plus matching city despite an outdated street address.
    supported=primary.location_strong and primary.score>=72
    name_and_city=primary.city_match and primary.zip_match and primary.name_score>=92 and primary.score>=55
    supported=supported or name_and_city
    competitors=[x for x in candidates[1:] if x.location_strong and x.score>=70 and x.score>=primary.score-17]
    if supported and competitors:
        status='MULTIPLE_ACCOUNTS';reason='Multiple CRM accounts share strongly matching physical location'
    elif supported:
        status='CONFIDENT_MATCH' if primary.location_strong and primary.score>=88 else 'REVIEW_MATCH'
        reason='' if status=='CONFIDENT_MATCH' else 'Match relies on partial evidence; review address/name'
    else:
        status='NO_MATCH' if primary.score<60 else 'AMBIGUOUS'
        reason='Insufficient independent identity evidence'
    # If two accounts score nearly the same without strong location proof, don't choose one.
    if status in ('CONFIDENT_MATCH','REVIEW_MATCH') and len(candidates)>1 and candidates[1].score>=primary.score-6 and candidates[1].city_match and not primary.location_strong:
        status='AMBIGUOUS';reason='Near-tied candidates without verified address'
    return {'match_status':status,'top':asdict(primary),'candidates':[asdict(x) for x in candidates],'ambiguity_reason':reason}
