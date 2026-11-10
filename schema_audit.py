"""Read-only API schema discovery and comparison. Sends only GET requests."""
import json,os,sys
from pathlib import Path
from urllib.parse import urljoin
import requests
from dotenv import load_dotenv

BASE='https://analyst-assessment-production.up.railway.app'
PATHS=['/api/openapi.json','/openapi.json','/api/v1/openapi.json','/api/swagger.json','/swagger.json','/api/docs-json','/api/v1/swagger.json']
REQUIRED_UPDATE={'parent_id','name','billing_street','billing_city','billing_state','billing_zip','chow_current_account'}
REQUIRED_CREATE={'name','parent_id','billing_street','billing_city','billing_state','billing_zip'}

def resolve_ref(node,spec):
    seen=set()
    while isinstance(node,dict) and '$ref' in node:
        ref=node['$ref']
        if ref in seen:break
        seen.add(ref)
        if not ref.startswith('#/'):break
        out=spec
        for k in ref[2:].split('/'):
            out=out.get(k,{})
        node=out
    return node

def request_fields(operation,spec):
    body=resolve_ref(operation.get('requestBody',{}),spec)
    contents=body.get('content',{})
    schema=contents.get('application/json',{}).get('schema',{})
    schema=resolve_ref(schema,spec)
    if 'allOf' in schema:
        fields=set(); req=set()
        for component in schema['allOf']:
            props,required=request_fields({'requestBody':{'content':{'application/json':{'schema':component}}}},spec)
            fields |= props;req |= required
        return fields,req
    return set(schema.get('properties',{})),set(schema.get('required',[]))

def inspect(spec):
    paths=spec.get('paths',{})
    actions=[]
    for path, methods in paths.items():
        if not isinstance(methods,dict) or 'account' not in path.lower():continue
        for method,entry in methods.items():
            if method.lower() not in ('post','patch','put'):continue
            fields,required=request_fields(entry,spec)
            actions.append({'method':method.upper(),'path':path,'fields':sorted(fields),'required':sorted(required), 'missing_expected_update': sorted(REQUIRED_UPDATE-fields) if method.lower() in ('patch','put') else [],'missing_expected_create':sorted(REQUIRED_CREATE-fields) if method.lower()=='post' else []})
    return {'schema_available':True,'schema_version':spec.get('openapi',spec.get('swagger','unknown')),'account_mutations':actions,'verification':'Compare fields and path parameters before enabling any CRM writes. This audit performs no writes.'}

def main():
    load_dotenv()
    token=os.getenv('CRM_API_TOKEN','').strip()
    if not token:
        sys.exit('CRM_API_TOKEN missing in .env; no requests made')
    headers={'Authorization':f'Bearer {token}','Accept':'application/json'}
    sess=requests.Session(); report={'schema_available':False,'checked_urls':[],'account_mutations':[], 'verification':'UNVERIFIED. No CRM writes permitted.'}
    for path in PATHS:
        url=urljoin(BASE,path)
        try:
            r=sess.get(url,headers=headers,timeout=12)
            report['checked_urls'].append({'path':path,'status':r.status_code})
            if r.ok:
                content=r.json()
                if isinstance(content,dict) and 'paths' in content:
                    report=inspect(content)
                    report['source_path']=path
                    Path('output').mkdir(exist_ok=True)
                    Path('output/openapi_snapshot.json').write_text(json.dumps(content,indent=2),encoding='utf-8')
                    break
        except (requests.RequestException,ValueError) as e:
            report['checked_urls'].append({'path':path,'error':type(e).__name__})
    Path('output').mkdir(exist_ok=True)
    Path('output/schema_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    if not report['schema_available']:
        print('No machine-readable OpenAPI specification found. Inspect /api/docs manually and do NOT enable writeback.')

if __name__=='__main__':main()
