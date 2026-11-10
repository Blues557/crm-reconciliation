"""Pure, conservative normalization helpers for CRM / website comparisons."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

STREET = {'street':'st','st':'st','road':'rd','rd':'rd','avenue':'ave','ave':'ave','boulevard':'blvd','blvd':'blvd', 'drive':'dr','dr':'dr','lane':'ln','ln':'ln','court':'ct','ct':'ct','place':'pl','pl':'pl','circle':'cir','cir':'cir','parkway':'pkwy','pkwy':'pkwy','highway':'hwy','hwy':'hwy','north':'n','south':'s','east':'e','west':'w','northeast':'ne','northwest':'nw','southeast':'se','southwest':'sw','route':'rt','terrace':'ter','ter':'ter','pike':'pike','pk':'pike','westbound':'w'}
STATES = {'ohio':'OH','michigan':'MI','pennsylvania':'PA','indiana':'IN','colorado':'CO'}
CARE_ALIASES = {'assisted living':'assisted_living','al':'assisted_living','memory support':'memory_care','memory care':'memory_care','skilled nursing':'nursing_rehab','short term rehabilitation and nursing':'nursing_rehab','rehabilitation and nursing':'nursing_rehab','nursing and rehabilitation':'nursing_rehab'}

def clean(v):
    v = unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode().lower().replace('&',' and ')
    return ' '.join(re.findall(r'[a-z0-9]+',v))

def name(v):
    return clean(v)

def address(v):
    return ' '.join(STREET.get(t,t) for t in clean(v).split())

def is_po_box(v):
    return bool(re.search(r'\b(?:p\s*o\s*box|post\s+office\s+box)\b',clean(v)))

def city(v): return clean(v)

def state(v):
    s = str(v or '').strip()
    return STATES.get(s.lower(), s.upper())

def zipcode(v):
    s = str(v or '').strip()
    if re.fullmatch(r'\d{5}\.0',s): s=s[:-2]
    m=re.match(r'^(\d{5})(?:-\d{4})?$',s)
    return m.group(1) if m else ''

def care(v):
    found=set()
    for part in re.split(r'[|,;/]+',str(v or '')):
        key=clean(part)
        if key: found.add(CARE_ALIASES.get(key,key))
    return found

def money(v):
    try: return Decimal(str(v or '0').replace(',','').replace('$',''))
    except InvalidOperation: raise ValueError(f'Invalid financial amount: {v!r}')

def facility_key(row):
    """Stable website identity; used for proposal fingerprints, not as a universal global ID."""
    return '|'.join((state(row.get('state')),zipcode(row.get('zip')),address(row.get('address')),city(row.get('city'))))
