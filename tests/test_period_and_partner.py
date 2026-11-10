from datetime import datetime
from pathlib import Path
import pytest
from app.dates import date_key,in_scope,windows
from app.collector import KST,ingest
from app.partner import parse_rows,fetch_board,BOARDS,detail_fields,get_link,soup_of
from app.attachments import extract,AttachmentError

def test_strict_start_and_date_formats():
    assert date_key('20261001')=='2026-10-01'
    assert date_key('26.10.01 , 13시')=='2026-10-01'
    assert not in_scope('2026-09-30') and in_scope('2026/10/01')
    assert not in_scope('') and not date_key('2026-02-31')

def test_split_covers_entire_historical_period():
    start=datetime(2026,10,1,tzinfo=KST);end=datetime(2026,11,10,14,tzinfo=KST)
    ranges=list(windows(start,end))
    assert ranges[0][0]==start and ranges[-1][1]==end
    assert all(a[1]==b[0] for a,b in zip(ranges,ranges[1:]))
    assert all((b-a).days<=7 for a,b in ranges)

def test_history_import_keeps_real_first_seen_and_excludes_old_record():
    now=datetime(2026,11,10,14,tzinfo=KST)
    state={'records':[]};seen={};fresh=[]
    rows=[{'id':'old','fingerprint':'x','date':'20260930','stage':'입찰공고'},{'id':'oct','fingerprint':'y','date':'20261002','stage':'입찰공고'}]
    ingest(rows,state,seen,fresh,now,True)
    assert len(fresh)==1 and fresh[0]['id']=='oct'
    assert fresh[0]['first_seen'].startswith('2026-11-10') and fresh[0]['historical_import']
    assert fresh[0]['publication_date']=='2026-10-02'

def test_partner_reads_visible_post_link_without_inventing_url():
    a=soup_of('''<a onclick="submitParam('tech_app_view.asp', '', 'idx=109');">보기</a>''').a
    assert get_link(a,'https://partner.lh.or.kr/technology/tech_app_list.asp')=='https://partner.lh.or.kr/technology/tech_app_view.asp?idx=109'

def test_partner_public_result_date_is_review_date():
    raw="""<table><caption>자재ㆍ공법 선정심의 결과표</caption><tr><td>성남금토 공사</td><td>LH</td><td>2026.10.15</td><td>교량</td><td>업체</td><td><a onclick='openResultView(1734);'>보기</a></td></tr></table>$$1"""
    rows,pages=parse_rows(raw,'선정심의 결과','/deliberate/deliberate_innerList.asp')
    assert rows[0]['list_date']=='2026-10-15' and rows[0]['list_date_label']=='심의일'
    assert rows[0]['post']=={'rr_idx':'1734'} and pages==1

def test_partner_stops_before_old_detail_and_does_not_treat_it_as_new():
    class Client:
        def request(self,*args):return '''<h4>자재공법 선정심의 계획 및 공모</h4><table><tr><td>성남금토 공사</td><td>공법</td><td>25.06.02 ~ 25.06.16</td><td>업체선정</td><td>심의</td><td><a onclick="openView(1571);">보기</a></td></tr></table>'''
    found,status=fetch_board(Client(),BOARDS[0],'2026-11-10',{})
    assert not found and status['status']=='성공' and status['excluded_before_start']==1

def test_detail_date_is_not_validity_period_or_view_count():
    box,fields=detail_fields('<table><tr><th>작성일</th><td>2026.10.03</td><th>조회수</th><td>100</td></tr></table>')
    assert fields['작성일']=='2026.10.03'

def test_unreadable_attachment_is_not_empty_text():
    with pytest.raises(AttachmentError):extract(b'unknown binary','sample.hwp')

def test_render_keeps_only_requested_original_dates(tmp_path,monkeypatch):
    import json
    from app import render
    data=tmp_path/'state.json'
    data.write_text(json.dumps({'start_date':'2026-10-01','records':[{'id':'sept','title':'성남금토 이전 자료','date':'20260930','service':'LH 전자조달'},{'id':'oct','title':'성남금토 기준일 자료','date':'20261001','service':'LH 전자조달'}],'runs':[]}))
    monkeypatch.setattr(render,'DATA',data);monkeypatch.setattr(render,'SITE',tmp_path/'site')
    render.run()
    records=json.loads((tmp_path/'site/data/records.json').read_text())
    assert [r['id'] for r in records]==['oct']
    assert (tmp_path/'site/history/2026-10-01.html').exists()
    assert not (tmp_path/'site/history/2026-09-30.html').exists()

def test_daily_collection_recovers_a_gap_longer_than_three_days(tmp_path,monkeypatch):
    import json
    from app import collector
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,11,10,14,tzinfo=KST)
    (tmp_path/'state.json').write_text(json.dumps({'records':[],'fingerprints':{},'runs':[{'complete':True,'checked_at':'2026-10-10T09:00:00+09:00'}]}))
    monkeypatch.setattr(collector,'DATA',tmp_path);monkeypatch.setattr(collector,'datetime',Clock)
    monkeypatch.delenv('DATA_GO_KR_KEY',raising=False)
    collector.run(3)
    state=json.loads((tmp_path/'state.json').read_text())
    assert state['runs'][0]['query_from'].startswith('2026-10-09')

def test_plans_without_notice_number_do_not_merge_different_periods():
    from app.collector import normalize
    a=normalize({'bsnsNm':'성남금토 기반시설','aprvlDt':'20261005','orderExpectYr':'2026','orderExpectMonth':'10'},'LH 전자조달','발주계획','발주계획')
    b=normalize({'bsnsNm':'성남금토 기반시설','aprvlDt':'20261005','orderExpectYr':'2026','orderExpectMonth':'11'},'LH 전자조달','발주계획','발주계획')
    assert a['id']!=b['id']

def test_legacy_plan_link_survives_identity_migration_without_fake_revision():
    now=datetime(2026,11,10,14,tzinfo=KST)
    legacy={'id':'public-old','fingerprint':'old-fp','title':'성남금토 계획','service':'LH 전자조달','base_stage':'발주계획','stage':'발주계획','date':'20261022','agency':'LH','amounts':[],'first_seen':'2026-11-10T13:00:00+09:00'}
    item={k:v for k,v in legacy.items() if k!='first_seen'};item.update(id='strong-new-key',fingerprint='new-fp')
    state={'records':[legacy]};seen={'public-old':'old-fp'};fresh=[]
    ingest([item],state,seen,fresh,now,True)
    assert not fresh and state['records'][0]['id']=='public-old'
    assert state['records'][0]['source_identity']=='strong-new-key'
    assert state['records'][0]['first_seen']=='2026-11-10T13:00:00+09:00'
