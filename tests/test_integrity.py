import json
from datetime import datetime
import pytest
from app.collector import FeedError, parse_response, request_params, SOURCES, CONTRACTS, KST, fetch_source, normalize

def test_unknown_json_is_not_empty_success():
    with pytest.raises(FeedError): parse_response('{"error":"denied"}')

def test_html_error_is_not_empty_success():
    with pytest.raises(FeedError): parse_response('<html><body>Service unavailable</body></html>')

def test_empty_requires_explicit_count():
    with pytest.raises(FeedError): parse_response('<response><header><resultCode>00</resultCode></header><body/></response>')
    assert parse_response('{"response":{"header":{"resultCode":"00"},"body":{"totalCount":0,"items":""}}}') == []

def test_auth_error_not_no_notices():
    with pytest.raises(FeedError) as ex: parse_response('<response><header><resultCode>30</resultCode></header></response>')
    assert ex.value.code=='api_30'

def test_all_operations_exist_in_official_schema():
    official={'https://'+c['host']+'/'+op for c in CONTRACTS.values() for op in c['operations']}
    assert all(s[2] in official for s in SOURCES)

def test_source_specific_parameters_are_official():
    start=datetime(2026,11,3,tzinfo=KST);end=datetime(2026,11,10,tzinfo=KST)
    for source in SOURCES:
        params=request_params(source,'dummy',start,end)
        schema=next(c for c in CONTRACTS.values() if source[2].startswith('https://'+c['host']+'/'))
        operation=source[2].rsplit('/',1)[1]
        names={p['name'] for p in schema['operations'][operation]['parameters']}
        assert set(params)<=names

def test_lh_fields_and_amount_labels():
    row=normalize({'bidnmKor':'성남금토 A-4BL','bidNum':'123','bidDegree':'2','fdmtlAmt':'100'},'LH 전자조달','입찰공고','입찰공고')
    assert row['notice_id']=='123' and row['sequence']=='2'
    assert row['amounts'][0]['label']=='기초금액'
    assert not row['source_detail_verified']

def test_lh_contract_fields():
    row=normalize({'ctrctNm':'성남금토 기반시설','bidNum':'C1','ctrctAmt':'200'},'LH 전자조달','계약','계약')
    assert row['amounts'][0]['label']=='계약금액'
    assert row['areas']==['기반시설']

def test_no_unsupported_geumto1_inference():
    row=normalize({'bidNtceNm':'성남금토 공고'},'나라장터','입찰','입찰공고')
    assert row['areas']==['지역미분류']

def test_repeating_page_fails():
    class Response:
        status_code=200
        text=json.dumps({'response':{'header':{'resultCode':'00'},'body':{'totalCount':200,'items':[{'bidNtceNm':'성남금토','bidNtceNo':str(i)} for i in range(100)]}}})
    class Session:
        def get(self,*args,**kwargs): return Response()
    with pytest.raises(FeedError) as ex: fetch_source(Session(),SOURCES[0],'dummy',datetime.now(KST))
    assert ex.value.code=='repeated_page'

def test_gateway_json_error_code():
    with pytest.raises(FeedError) as ex: parse_response('{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"returnReasonCode":"10"}}}')
    assert ex.value.code=='api_10'

def test_missing_key_records_eight_unconfigured_services(tmp_path,monkeypatch):
    from app import collector
    monkeypatch.setattr(collector,'DATA',tmp_path)
    monkeypatch.delenv('DATA_GO_KR_KEY',raising=False)
    monkeypatch.setenv('REQUIRE_COMPLETE_RUN','1')
    assert collector.run(7)==2
    state=json.loads((tmp_path/'state.json').read_text())
    latest=state['runs'][0]
    assert latest['total_services']==8
    assert latest['successful_services']==0 and not latest['complete']
    assert all(s['code']=='missing_key' for s in latest['statuses'])
    assert state['records']==[]
