"""Read-only Bellhaven website and CRM collection and diagnostics.

Run: python collect.py
All requests are GET. No CRM modifications are performed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
BASE = 'https://analyst-assessment-production.up.railway.app'
API_BASE = BASE + '/api/v1'
OUT = Path('data')
OUT.mkdir(exist_ok=True)
TOKEN = os.getenv('CRM_API_TOKEN', '').strip()
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Bellhaven-Reconciliation-Assessment/0.1'})
TIMEOUT = 25


def get(url: str, *, auth: bool = False, params: dict | None = None) -> requests.Response:
    headers = {'Authorization': f'Bearer {TOKEN}'} if auth else {}
    for attempt in range(3):
        try:
            response = SESSION.get(url, headers=headers, params=params, timeout=TIMEOUT)
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError('Unreachable')


def decode_records(payload):
    """Get list payloads without assuming CRM pagination schema."""
    if isinstance(payload, list):
        return payload, {}
    if isinstance(payload, dict):
        for key in ('accounts', 'results', 'items', 'data', 'records'):
            value = payload.get(key)
            if isinstance(value, list):
                return value, payload
            if isinstance(value, dict):
                for inner in ('accounts', 'results', 'items', 'records'):
                    if isinstance(value.get(inner), list):
                        return value[inner], {**payload, **value}
    return [], payload if isinstance(payload, dict) else {}


def collect_crm():
    if not TOKEN:
        print('CRM_API_TOKEN not set; skipping CRM. Copy .env.example to .env and set it.')
        return []
    rows, seen_ids, seen_pages = [], set(), set()
    next_url, params = API_BASE + '/accounts', {'page': 1, 'limit': 100}
    for iteration in range(50):
        page_key = (next_url, tuple(sorted((params or {}).items())))
        if page_key in seen_pages:
            break
        seen_pages.add(page_key)
        response = get(next_url, auth=True, params=params)
        payload = response.json()
        if iteration == 0:
            (OUT / 'crm_first_response_shape.json').write_text(json.dumps({
                'root_type': type(payload).__name__,
                'top_level_keys': list(payload) if isinstance(payload, dict) else [],
                'sample_account_keys': list(decode_records(payload)[0][0]) if decode_records(payload)[0] and isinstance(decode_records(payload)[0][0], dict) else [],
                'pagination_keys': [k for k in ('next','next_page','page','pages','total','total_pages','has_more','pagination','meta') if isinstance(payload,dict) and k in payload],
            }, indent=2), encoding='utf-8')
        batch, meta = decode_records(payload)
        new_count = 0
        for row in batch:
            if not isinstance(row, dict):
                continue
            marker = str(row.get('id') or json.dumps(row,sort_keys=True))
            if marker not in seen_ids:
                rows.append(row); seen_ids.add(marker); new_count += 1
        print(f'CRM page {iteration+1}: {len(batch)} rows, {new_count} new')
        if not batch or new_count == 0:
            break
        next_value = meta.get('next') or meta.get('next_page')
        pagination = meta.get('pagination') if isinstance(meta.get('pagination'),dict) else {}
        if not next_value:
            next_value = pagination.get('next') or pagination.get('next_page')
        if isinstance(next_value, str) and (next_value.startswith('/') or next_value.startswith('http')):
            next_url = urljoin(BASE, next_value); params = None
        elif isinstance(next_value, int) and not isinstance(next_value,bool):
            next_url = API_BASE + '/accounts'; params = {'page': next_value, 'limit': 100}
        else:
            current_page = (params or {}).get('page', iteration+1)
            page_total = meta.get('total_pages') or pagination.get('total_pages') or meta.get('pages')
            if page_total is not None and current_page >= int(page_total):
                break
            # Some APIs cap limit below 100; continue until an empty/repeated page.
            next_url = API_BASE + '/accounts'; params = {'page': current_page+1, 'limit': 100}
    (OUT / 'crm_accounts_raw.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    pd.json_normalize(rows).to_csv(OUT / 'crm_accounts.csv', index=False)
    print('Saved CRM accounts:', len(rows))
    return rows


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def normalize_name(text):
    text = clean(text).casefold().replace('&',' and ')
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def address_from_schema(soup):
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(tag.string or tag.get_text())
        except (ValueError,TypeError):
            continue
        nodes = parsed if isinstance(parsed,list) else [parsed]
        for node in nodes:
            if isinstance(node,dict):
                nodes_to_check = node.get('@graph',[]) if isinstance(node.get('@graph'),list) else []
                for entity in [node]+nodes_to_check:
                    if isinstance(entity,dict) and isinstance(entity.get('address'),dict):
                        return entity['address']
    return {}


def detail_page(url):
    response = get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.select_one('h1')
    name = clean(title.get_text(' ', strip=True) if title else '')
    address = address_from_schema(soup)
    street = clean(address.get('streetAddress', ''))
    city = clean(address.get('addressLocality', ''))
    state = clean(address.get('addressRegion', ''))
    postal = clean(address.get('postalCode', ''))

    # The assessment pages often render a simple 'Address' label followed
    # by street and 'City, ST ZIP' instead of JSON-LD or <address> markup.
    main = soup.select_one('main') or soup.body or soup
    lines = [clean(t) for t in main.stripped_strings if clean(t)]
    def section(label):
        positions = [i for i, t in enumerate(lines) if t.casefold() == label.casefold()]
        if not positions:
            return []
        index = positions[0] + 1
        stop = {'address', 'care offerings', 'administrator', 'phone'}
        values = []
        for value in lines[index:]:
            if value.casefold() in stop:
                break
            values.append(value)
        return values

    address_lines = section('Address')
    location_re = re.compile(r'^(.+?),\s*([A-Za-z]{2})\s+(\d{5})(?:-\d{4})?$')
    for idx, line in enumerate(address_lines):
        match = location_re.match(line)
        if match:
            if not city:
                city = match.group(1).strip()
            if not state:
                state = match.group(2).upper()
            if not postal:
                postal = match.group(3)
            if not street and idx > 0:
                street = clean(' '.join(address_lines[:idx]))
            break
    if not street and address_lines:
        street = address_lines[0]

    care_lines = section('Care Offerings')
    care = ' | '.join(dict.fromkeys(care_lines))
    return {
        'name': name, 'address': street, 'city': city, 'state': state,
        'zip': postal, 'care_offerings': care, 'source_url': url,
        'needs_address_review': not bool(street and city and state and postal)
    }


def collect_website():
    discovered = set()
    page_summaries = []
    # Pagination and path variants are deliberately checked rather than assuming one site's markup.
    candidates = [BASE+'/communities']+[BASE+f'/communities?page={p}' for p in range(2,15)]
    total_pages = None
    for page_index, url in enumerate(candidates, start=1):
        if total_pages is not None and page_index > total_pages:
            break
        try:
            response = get(url)
        except requests.RequestException as exc:
            print('Website listing error:',url, str(exc)[:140]); continue
        soup = BeautifulSoup(response.text,'html.parser')
        if total_pages is None:
            listing_text = soup.get_text(' ', strip=True)
            page_match = re.search(r'Page\s+\d+\s+of\s+(\d+)', listing_text, re.I)
            if page_match:
                total_pages = int(page_match.group(1))
                print('Detected directory page count:', total_pages)
        matches = set()
        for link in soup.find_all('a',href=True):
            absolute = urljoin(BASE,link['href'])
            parsed = urlparse(absolute)
            if parsed.netloc != urlparse(BASE).netloc:
                continue
            path = parsed.path.rstrip('/')
            if path.startswith('/communities/') and path.count('/') == 2 and path != '/communities':
                matches.add(BASE+path)
        page_summaries.append({'listing_url':url,'detail_links':len(matches)})
        discovered.update(matches)
        print('Website listing',url,'detail URLs:',len(matches))
        if len(page_summaries)>1 and not matches:
            break
    # Detail pages can be linked from the home page but absent from the directory.
    try:
        home = BeautifulSoup(get(BASE).text,'html.parser')
        for link in home.find_all('a',href=True):
            absolute = urljoin(BASE,link['href'])
            parsed = urlparse(absolute)
            if parsed.netloc == urlparse(BASE).netloc and re.fullmatch(r'/communities/[^/]+/?', parsed.path):
                discovered.add(BASE+parsed.path.rstrip('/'))
    except requests.RequestException as exc:
        print('Homepage links unavailable:',str(exc)[:140])
    records = []
    for url in sorted(discovered):
        try:
            records.append(detail_page(url))
        except requests.RequestException as exc:
            print('Detail error:',url,str(exc)[:140])
    (OUT / 'website_listing_diagnostics.json').write_text(json.dumps(page_summaries,indent=2),encoding='utf-8')
    (OUT / 'website_locations_raw.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
    pd.DataFrame(records,columns=['name','address','city','state','zip','care_offerings','source_url','needs_address_review']).to_csv(OUT/'website_locations.csv',index=False)
    print('Saved website detail pages:',len(records),'address-review:',sum(x['needs_address_review'] for x in records))
    return records


def profile(crm, facilities):
    parent_counts = {}
    for account in crm:
        parent = str(account.get('parent_id'))
        parent_counts[parent] = parent_counts.get(parent,0)+1
    profile_data = {
        'crm_count':len(crm), 'website_count':len(facilities),
        'crm_field_names':sorted(set(k for a in crm for k in a.keys())),
        'crm_parent_counts':parent_counts,
        'website_missing_structured_address':sum(f['needs_address_review'] for f in facilities),
        'website_name_duplicates':pd.Series([normalize_name(f['name']) for f in facilities]).value_counts().loc[lambda x: x>1].to_dict() if facilities else {},
        'warning':'Do not treat website absence as ownership proof. No changes performed.'
    }
    (OUT/'profile.json').write_text(json.dumps(profile_data,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(profile_data,indent=2,ensure_ascii=False)[:4000])


if __name__ == '__main__':
    print('READ-ONLY COLLECTION — no POST/PATCH/PUT/DELETE calls')
    try:
        crm = collect_crm()
        facilities = collect_website()
        profile(crm,facilities)
    except Exception as exc:
        print('Collection failed:',type(exc).__name__,str(exc)[:500],file=sys.stderr)
        sys.exit(1)
