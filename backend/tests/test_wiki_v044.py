"""Public synthetic contract fixtures; no private cases or live model calls."""
import copy
import json
import subprocess
import sys

import pytest
from evals import wiki_v044 as w
from evals.wiki_v044_prepare import prepare


@pytest.fixture
def sample():
    base = {'term':'대기열','user_note':{'text':'나중 항목을 먼저 꺼낸다. 작업은 항상 성공한다.','trust':'unverified'},
            'sources':{'1':'대기열은 먼저 넣은 항목을 먼저 꺼낸다.'}}
    policy = {'definition_available':True,'example_mode':'required',
              'correction':{'status':'required','items':[{'note_quote':'나중 항목을 먼저 꺼낸다','replacement':'먼저 넣은 항목을 먼저 꺼낸다','source_ids':['1']}]},
              'open_claims':[{'id':'U1','note_quote':'작업은 항상 성공한다','issue':'성공 보장 여부'}]}
    output = {'response_kind':'full','summary':['먼저 넣은 항목을 먼저 꺼낸다.[1]'],
              'sections':{'definition':'먼저 넣은 항목을 먼저 꺼내는 구조다.[1]','mechanism':None,
                          'example':'가령 대기 작업 A와 B가 있다면 먼저 넣은 A를 먼저 꺼낸다.[1]','cautions':None},
              'corrections':copy.deepcopy(policy['correction']['items']),
              'limitations':[{'claim_id':'U1','text':'성공 보장 여부는 확인할 수 없다.'}], 'source_ids':['1']}
    return base, policy, output


@pytest.mark.parametrize('stage', ['evidence','correction','generation'])
def test_request_prompt_and_whitelist(sample,stage):
    base,p,_=sample
    envelope=prepare(stage,base,p if stage=='generation' else None)
    req=envelope['request'];payload=json.loads(req['messages'][0]['content'][0]['text'])
    assert req['system'][0]['text']==(w.ROOT/(stage+'.txt')).read_text(encoding='utf8')
    assert set(payload)==({'term','sources'} if stage=='evidence' else set(base)|({'policy'} if stage=='generation' else set()))
    assert envelope['request_hash']==w.digest(req)
    assert envelope['model_calls']==0


def test_mock_pipeline_and_cache(sample):
    base,p,_=sample; calls=[];cache=w.EvidenceCache()
    def mock(req):
        payload=json.loads(req['messages'][0]['content'][0]['text']);calls.append(payload)
        return {k:copy.deepcopy(p[k]) for k in (w.CORRECTION['required'] if 'user_note' in payload else w.EVIDENCE['required'])}
    a=w.prepare_prediction(base,mock,cache);b=w.prepare_prediction(base,mock,cache)
    assert a==b and len(calls)==3
    assert sum('user_note' not in x for x in calls)==1
    assert json.loads(a['generation_request']['messages'][0]['content'][0]['text'])['policy']==p


@pytest.mark.parametrize('url',['[참고](//example.invalid/path)','HTTPS://example.invalid','<https:example.invalid>', 'WWW.example.invalid'])
def test_generated_urls_rejected_but_note_quote_preserved(sample,url):
    b,p,o=sample
    p['correction']['items'][0]['replacement']+=' '+url;o['corrections']=copy.deepcopy(p['correction']['items'])
    with pytest.raises(ValueError,match='correction_url'):w.validate_policy(b,p)
    with pytest.raises(ValueError,match='correction_url'):w.validate_output(o,b,p)
    p['correction']['items'][0]['replacement']='먼저 넣은 항목을 먼저 꺼낸다'
    quote=p['correction']['items'][0]['note_quote'];new=quote+' '+url+' [999]'
    b['user_note']['text']=b['user_note']['text'].replace(quote,new);p['correction']['items'][0]['note_quote']=new
    o['corrections']=copy.deepcopy(p['correction']['items']);before=copy.deepcopy(o)
    assert w.validate_output(o,b,p)['semantic_status']=='NOT_EVALUATED' and o==before
    o['sections']['cautions']=url
    with pytest.raises(ValueError,match='url'):w.validate_output(o,b,p)


@pytest.mark.parametrize('citation',['[1]','[999]','[ 999 ]'])
def test_correction_citation_is_ids_only(sample,citation):
    b,p,_=sample;p['correction']['items'][0]['replacement']+=citation
    with pytest.raises(ValueError,match='correction_inline_citation'):w.validate_policy(b,p)


@pytest.mark.parametrize('aliases',[('',),(' ',),'대기열',None,{'대기열'},('x','X')])
def test_aliases_rejected_before_transport(sample,aliases):
    b,_,_=sample
    def never(req):raise AssertionError('transport called')
    with pytest.raises(ValueError,match='aliases_'):w.prepare_prediction(b,never,w.EvidenceCache(),aliases)


def test_guard_keeps_limited_example_and_correction(sample):
    b,p,_=sample;b['term']='다른 용어'
    result,audit=w.assemble(b,{k:p[k] for k in w.EVIDENCE['required']},{k:p[k] for k in w.CORRECTION['required']})
    assert not result['definition_available'] and audit['guard_applied']
    assert result['example_mode']=='required' and result['correction']==p['correction']


@pytest.mark.parametrize('bad_id',['Z99','U2'])
def test_claim_id_sequence(sample,bad_id):
    b,p,_=sample;p['open_claims'][0]['id']=bad_id
    with pytest.raises(ValueError,match='id_sequence'):w.validate_policy(b,p)


def test_duplicate_claim_span(sample):
    b,p,_=sample;p['open_claims'].append({**p['open_claims'][0],'id':'U2'})
    with pytest.raises(ValueError,match='duplicate_open_span'):w.validate_policy(b,p)


@pytest.mark.parametrize('mutation',['limit','example','definition','contract_error','citation'])
def test_output_contract_failures(sample,mutation):
    b,p,o=sample
    if mutation=='limit':o['limitations']=[]
    elif mutation=='example':o['sections']['example']=None
    elif mutation=='definition':o['sections']['definition']='인용 없는 정의'
    elif mutation=='contract_error':o['response_kind']='contract_error'
    else:o['source_ids']=['999']
    with pytest.raises(ValueError):w.validate_output(o,b,p)


def test_semantic_failure_is_not_promoted_to_quality_pass(sample):
    b,p,o=sample;o['limitations'][0]['text']='별개의 가격은 확인할 수 없다.'
    assert w.validate_output(o,b,p)=={'structural_status':'PASS','semantic_status':'NOT_EVALUATED'}


def test_prepare_cli_offline_exclusive_output(sample,tmp_path):
    b,_,_=sample;inp=tmp_path/'input.json';out=tmp_path/'request.json'
    inp.write_text(json.dumps(b,ensure_ascii=False),encoding='utf8')
    cmd=[sys.executable,'-m','evals.wiki_v044_prepare','evidence','--input',str(inp),'--output',str(out)]
    first=subprocess.run(cmd,capture_output=True,text=True)
    assert first.returncode==0,first.stderr
    assert json.loads(out.read_text(encoding='utf8'))==prepare('evidence',b)
    before=out.read_bytes();second=subprocess.run(cmd,capture_output=True,text=True)
    assert second.returncode==2 and out.read_bytes()==before
