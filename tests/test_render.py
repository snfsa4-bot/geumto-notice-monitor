import json
from app import render

def test_daily_reruns_preserve_earlier_events_and_escape(tmp_path,monkeypatch):
    data=tmp_path/'state.json';site=tmp_path/'site'
    record={'id':'abc','title':'<script>alert(1)</script>','notice_id':'N1','first_seen':'2026-11-10T09:00:00+09:00','observed_at':'2026-11-10T09:00:00+09:00','stage':'입찰공고','url':'javascript:alert(1)'}
    data.write_text(json.dumps({'records':[record],'runs':[{'date':'2026-11-10','checked_at':'2026-11-10T10:00:00+09:00','new_count':0,'complete':True,'statuses':[]},{'date':'2026-11-10','checked_at':'2026-11-10T09:00:00+09:00','new_count':1,'complete':True,'statuses':[]}]}))
    monkeypatch.setattr(render,'DATA',data);monkeypatch.setattr(render,'SITE',site)
    render.run()
    page=(site/'posts/2026-11-10.html').read_text()
    assert '새로 확인된 사항 1건' in page
    assert '당일 조회 2회' in page
    assert '<script>' not in page and 'javascript:' not in page
    assert (site/'notices/abc.html').exists()

def test_failed_empty_day_is_not_no_notices(tmp_path,monkeypatch):
    data=tmp_path/'state.json';data.write_text(json.dumps({'records':[],'runs':[{'date':'2026-11-10','complete':False,'statuses':[]}]}))
    monkeypatch.setattr(render,'DATA',data);monkeypatch.setattr(render,'SITE',tmp_path/'site')
    render.run()
    text=(tmp_path/'site/posts/2026-11-10.html').read_text()
    assert '조회 불완전' in text
    assert '신규 공고 없음' not in text
