"""Run entity resolution + classification + read-only proposal export."""
import argparse,csv,json
from collections import Counter
from pathlib import Path
from matcher import resolve
from classifier import classify,stale_accounts
from proposals import proposal

DEFAULT_PARENT='0015QAPLGS3FVYEEEM'  # discovered from the supplied CRM snapshot; override via --parent-id

def read_csv(path):
    with open(path,encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def run(crm_path,web_path,out_dir,parent_id=DEFAULT_PARENT):
    accounts=read_csv(crm_path); facilities=read_csv(web_path)
    if not accounts or not facilities:raise ValueError('Empty input data')
    if len({a['account_id'] for a in accounts})!=len(accounts):raise ValueError('Duplicate account IDs in CRM input')
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    by_id={a['account_id']:a for a in accounts}
    results=[]; proposals=[]
    for web in facilities:
        resolution=resolve(web,accounts)
        decision=classify(web,resolution,by_id,parent_id)
        p=proposal(web,resolution,decision,by_id,parent_id)
        if p: proposals.append(p)
        results.append({'website':web,'resolution':resolution,'decision':decision,'proposal_id':p['proposal_id'] if p else None})
    stale=stale_accounts(results,accounts,parent_id)
    report={'crm_count':len(accounts),'website_count':len(facilities),'parent_id':parent_id,'match_status_counts':dict(Counter(x['resolution']['match_status'] for x in results)),'classification_counts':dict(Counter(x['decision']['classification'] for x in results)),'proposal_action_counts':dict(Counter(p['action'] for p in proposals)),'stale_review_count':len(stale),'safety':'READ ONLY. No CRM mutation implemented; all proposals require human review.'}
    for name,value in [('matching_results.json',results),('proposals.json',proposals),('stale_account_review.json',stale),('summary.json',report)]:
        (out_dir/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
    with (out_dir/'matching_review.csv').open('w',newline='',encoding='utf-8-sig') as f:
        columns=['website_name','web_city','web_state','web_zip','match_status','classification','action','crm_account_id','crm_name','crm_parent','score','address_score','name_score','runner_up','runner_up_score','reason','source_url']
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for x in results:
            w=x['website'];r=x['resolution'];d=x['decision'];a=r['top'] or {};runner=r['candidates'][1] if len(r['candidates'])>1 else {}
            writer.writerow({'website_name':w['name'],'web_city':w['city'],'web_state':w['state'],'web_zip':w['zip'],'match_status':r['match_status'],'classification':d['classification'],'action':d['action'],'crm_account_id':a.get('account_id',''),'crm_name':a.get('crm_name',''),'crm_parent':a.get('parent_name',''),'score':a.get('score',''),'address_score':a.get('address_score',''),'name_score':a.get('name_score',''),'runner_up':runner.get('crm_name',''),'runner_up_score':runner.get('score',''),'reason':d['reason'],'source_url':w['source_url']})
    print(json.dumps(report,indent=2));return results,proposals,stale

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--crm',default='data/crm_accounts.csv');ap.add_argument('--website',default='data/website_locations.csv');ap.add_argument('--out',default='output');ap.add_argument('--parent-id',default=DEFAULT_PARENT)
    opt=ap.parse_args();run(opt.crm,opt.website,opt.out,opt.parent_id)
