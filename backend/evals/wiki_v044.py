"""v0.4.4 offline candidate. No SDK, credentials, network, retries or live entry point."""
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "prompts" / "wiki_v044"
VERSION = 'v0.4.4-r3-review'
MODEL = 'global.openai.gpt-6-luna'
def obj(p): return dict(type='object', properties=p, required=list(p), additionalProperties=False)
S = {'type':'string', 'minLength':1}
IDS = {'type':'array','items':S,'uniqueItems':True}
ITEM = obj({'note_quote':S,'replacement':S,'source_ids':IDS})
OPEN = obj({'id':S,'note_quote':S,'issue':S})
EVIDENCE = obj({'definition_available':{'type':'boolean'},'example_mode':{'type':'string','enum':['required','omit','review']}})
CORRECTION = obj({'correction':obj({'status':{'type':'string','enum':['none','required','unresolved']},'items':{'type':'array','items':ITEM}}),'open_claims':{'type':'array','items':OPEN}})
GEN = obj({'response_kind':{'type':'string','enum':['full','limited','contract_error']},'summary':{'type':'array','items':S,'minItems':1,'maxItems':3},'sections':obj({k:{'type':['string','null'],'minLength':1} for k in ['definition','mechanism','example','cautions']}),'corrections':{'type':'array','items':ITEM},'limitations':{'type':'array','items':obj({'claim_id':S,'text':S})},'source_ids':IDS})

def canonical(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v): return hashlib.sha256(canonical(v).encode()).hexdigest()
def check(ok, code):
    if not ok: raise ValueError(code)

def has_generated_url(text):
    """Recognize explicit links, not every occurrence of // or bare domain text."""
    return bool(re.search(
        r'(?i)(?:\b[a-z][a-z0-9+.-]*://|\b(?:https?|mailto|data|javascript):|\bwww\.'
        r'|\]\(\s*<?//[^\s/)>]+|<//[^\s/>]+'
        r'|(?<![\w/])//(?:[a-z0-9-]+(?:\.[a-z0-9-]+)+|localhost|\[[0-9a-f:]+\])(?=[:/\s?#)>]|$))',
        text))

def validate_replacement(item):
    # Generated replacement is checked; literal user note_quote is not generated text.
    text=item['replacement']
    check(not has_generated_url(text),'correction_url')
    # Correction attribution lives only in item.source_ids, never inline.
    check(not re.search(r'\[\s*\d+\s*\]',text),'correction_inline_citation')

def validate_aliases(aliases):
    check(type(aliases) in (list,tuple),'aliases_container')
    check(all(isinstance(x,str) and bool(x.strip()) and x==x.strip() for x in aliases),'aliases_value')
    check(len({x.casefold() for x in aliases})==len(aliases),'aliases_duplicate')
    return tuple(aliases)
def schema_check(v,s):
    types=s.get('type'); types=types if isinstance(types,list) else [types]
    matches={'object':isinstance(v,dict),'array':isinstance(v,list),'string':isinstance(v,str),'boolean':type(v)is bool,'null':v is None}
    check(any(matches.get(t,False) for t in types),'schema_type')
    if 'enum' in s: check(v in s['enum'],'schema_enum')
    if isinstance(v,str): check(bool(v.strip()) and len(v)>=s.get('minLength',0),'blank')
    if isinstance(v,dict):
        check(set(v)==set(s['required']),'schema_keys')
        for k,x in v.items(): schema_check(x,s['properties'][k])
    if isinstance(v,list):
        check(len(v)>=s.get('minItems',0) and len(v)<=s.get('maxItems',10**9),'array_size')
        if s.get('uniqueItems'): check(len({canonical(x) for x in v})==len(v),'duplicate')
        for x in v: schema_check(x,s['items'])

def clean(base):
    check(set(base)=={'term','user_note','sources'},'base_keys')
    check(isinstance(base['term'],str) and base['term'].strip(),'term')
    check(set(base['user_note'])=={'text','trust'} and base['user_note']['trust']=='unverified','note_role')
    check(isinstance(base['user_note']['text'],str),'note_text')
    check(isinstance(base['sources'],dict) and bool(base['sources']),'empty_sources_server_route')
    check(all(isinstance(k,str) and k.isdigit() and isinstance(v,str) and v.strip() for k,v in base['sources'].items()),'sources')
    return copy.deepcopy(base)

def request(stage,base,policy=None):
    base=clean(base)
    if stage=='evidence': payload={k:base[k] for k in ['term','sources']}; schema=EVIDENCE
    elif stage=='correction': payload=base; schema=CORRECTION
    elif stage=='generation':
        validate_policy(base,policy)
        check(policy['example_mode']!='review','review_required')
        payload={**base,'policy':copy.deepcopy(policy)};schema=GEN
    else: raise ValueError('stage')
    prompt=(ROOT/(stage+'.txt')).read_text(encoding='utf8')
    return {'modelId':MODEL,'system':[{'text':prompt}],'messages':[{'role':'user','content':[{'text':canonical(payload)}]}],'inferenceConfig':{'maxTokens':3000},'additionalModelRequestFields':{'reasoning':{'effort':'none'},'text':{'format':{'strict':True}}},'outputConfig':{'textFormat':{'type':'json_schema','structure':{'jsonSchema':{'name':'wiki_'+stage,'schema':canonical(schema)}}}}}

def validate_policy(base,p):
    check(isinstance(p,dict) and set(p)=={'definition_available','example_mode','correction','open_claims'},'policy_keys')
    schema_check({k:p[k] for k in EVIDENCE['required']},EVIDENCE)
    schema_check({k:p[k] for k in CORRECTION['required']},CORRECTION)
    c=p['correction']; opens=p['open_claims']
    check(bool(c['items'])==(c['status']=='required'),'correction_status')
    check(c['status']!='unresolved' or bool(opens),'unresolved_claim_missing')
    check(c['status']!='none' or not opens,'none_with_open_claim')
    check(len({x['id'] for x in opens})==len(opens),'duplicate_claim_id')
    for x in c['items']+opens: check(base['user_note']['text'].count(x['note_quote'])==1,'note_quote')
    for x in c['items']:
        check(bool(x['source_ids']) and set(x['source_ids'])<=set(base['sources']),'correction_citation')
        validate_replacement(x)
    spans=[(base['user_note']['text'].index(x['note_quote']),len(x['note_quote'])) for x in opens]
    check(len(set(spans))==len(spans),'duplicate_open_span')
    check(spans==sorted(spans),'open_claim_source_order')
    check([x['id'] for x in opens]==['U'+str(i+1) for i in range(len(opens))],'open_claim_id_sequence')
    # Distinct partially overlapping open spans are allowed for compound claims.
    # Their semantic distinctness needs review; identical spans are never allowed.
    for x in opens:
        for y in c['items']:
            a=base['user_note']['text'].index(x['note_quote']);b=base['user_note']['text'].index(y['note_quote'])
            check(a+len(x['note_quote'])<=b or b+len(y['note_quote'])<=a,'open_correction_overlap')
    return copy.deepcopy(p)

def assemble(base,evidence,correction,approved_aliases=()):
    base=clean(base)
    approved_aliases=validate_aliases(approved_aliases)
    schema_check(evidence,EVIDENCE);schema_check(correction,CORRECTION)
    p={**copy.deepcopy(evidence),**copy.deepcopy(correction)}
    hay='\n'.join(base['sources'].values()).casefold()
    # Absence is conservative; presence is never sufficient proof of a definition.
    linked=any(x.casefold() in hay for x in (base['term'],*approved_aliases))
    audit={'raw_definition_available':p['definition_available'],'guard_applied':not linked,'approved_aliases':list(approved_aliases)}
    if not linked: p['definition_available']=False
    return validate_policy(base,p),audit

class EvidenceCache:
    def __init__(self): self.values={}
    def resolve(self,base,fixture_transport):
        req=request('evidence',base); key=digest({'version':VERSION,'request':req})
        if key not in self.values:
            value=fixture_transport(copy.deepcopy(req));schema_check(value,EVIDENCE)
            self.values[key]=copy.deepcopy(value)
        return copy.deepcopy(self.values[key]),key

def prepare_prediction(base, fixture_transport, cache, approved_aliases=()):
    """Separated classifier wiring; no gold/anchors accepted by this interface.

    Caller supplies a transport. Review packet tests supply mocks exclusively.
    A future paid runner must add approval/ledger gates before any transport.
    """
    base=clean(base)
    approved_aliases=validate_aliases(approved_aliases)
    evidence,key=cache.resolve(base,fixture_transport)
    correction_request=request('correction',base)
    correction=fixture_transport(copy.deepcopy(correction_request))
    policy,guard=assemble(base,evidence,correction,approved_aliases)
    generation_request=request('generation',base,policy)
    return {'policy':policy,'guard':guard,'evidence_cache_key':key,
            'correction_request':correction_request,'generation_request':generation_request,
            'routing_identity':digest({'version':VERSION,'guard':guard,'request':generation_request})}

def citation_errors(o):
    errors=[]
    for i,s in enumerate(o['summary']):
        if not re.search(r'\[\d+\]',s): errors.append('summary_citation:'+str(i))
    if o['sections']['definition'] and not re.search(r'\[\d+\]',o['sections']['definition']): errors.append('definition_citation')
    return errors

def validate_output(o,base,p):
    validate_policy(base,p);schema_check(o,GEN)
    check(o['response_kind']!='contract_error','contract_error_no_retry')
    check(o['response_kind']==('full' if p['definition_available'] else 'limited'),'route')
    s=o['sections'];check((s['definition'] is not None)==p['definition_available'],'definition')
    check((s['example'] is not None)==(p['example_mode']=='required'),'example')
    check(p['example_mode']!='review','review_required')
    check(o['corrections']==p['correction']['items'],'corrections')
    for item in o['corrections']: validate_replacement(item)
    ids=[x['claim_id'] for x in o['limitations']]
    check(len(ids)==len(set(ids)) and set(ids)=={x['id'] for x in p['open_claims']},'open_claim_coverage')
    check(not citation_errors(o),'field_citation')
    body='\n'.join(o['summary']+[v for v in s.values() if v]+[x['text'] for x in o['limitations']])
    cited=set(re.findall(r'\[(\d+)\]',body))|{i for x in o['corrections'] for i in x['source_ids']}
    check(bool(cited) and cited==set(o['source_ids']) and cited<=set(base['sources']),'citation_set')
    check(not has_generated_url(body),'url')
    return {'structural_status':'PASS','semantic_status':'NOT_EVALUATED'}
