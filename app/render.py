"""Render latest notices, immutable revision history, and daily query status."""
import html
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse
from app.collector import atomic_write
from app.dates import START_DATE,date_key,in_scope
from app.linking import merge_latest,explicit_related
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/state.json'
SITE=ROOT/'site'
def e(value): return html.escape(str(value or ''),quote=True)
def page(title,content):
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} | 금토 공고기록</title><link rel="stylesheet" href="../assets/style.css"></head><body><div class="shell"><header class="topbar"><a class="brand" href="../index.html">금토 공고기록</a><a href="../index.html">전체 기록</a></header><main><h1>{e(title)}</h1>{content}</main><footer>성남금토 공공조달 모니터링 · 비공식 주민 정보 서비스</footer></div></body></html>'
def item_block(r,detail=False):
    amounts=' / '.join(x['label']+' '+x['value']+'원' for x in r.get('amounts',[])) or '금액 미확인'
    label=r.get('date_label','원자료 기준일')
    text=f'<article class="post-item"><p>{e(r.get("service"))} · {e(r.get("stage"))}</p><h2>{e(r.get("title"))}</h2><p>공고번호 {e(r.get("notice_id") or "미제공")} · 차수 {e(r.get("sequence") or "미제공")}</p><p>기관 {e(r.get("agency"))} · 업체 {e(r.get("vendor") or "미확인")}</p><p>{e(amounts)}</p><p>{e(label)} {e(r.get("date") or "미제공")}<br>최초 확인 {e(r.get("first_seen"))}<br>이번 확인 {e(r.get("observed_at",r.get("first_seen")))}</p>'
    u=r.get('url','')
    if urlparse(u).scheme in ('https','http'):
        label='원문 확인' if r.get('source_detail_verified') else '공식 사이트에서 공고번호 검색'
        text+=f'<a href="{e(u)}" target="_blank" rel="noopener noreferrer">{label} ↗</a>'
    if not detail: text+=f' <a href="../notices/{e(r["id"])}.html">상세 기록</a>'
    if r.get('historical_import'):text+='<p>과거 자료 추가 · 당일 신규 공고와 구분</p>'
    for attachment in r.get('attachments',[]):
        link=attachment.get('url','')
        if urlparse(link).scheme=='https' and urlparse(link).hostname=='partner.lh.or.kr':text+=f'<p><a href="{e(link)}" target="_blank" rel="noopener noreferrer">첨부 원문 · {e(attachment.get("name"))}</a></p>'
    if r.get('opening_note'):text+=f'<p>{e(r["opening_note"])}</p>'
    return text+'</article>'
def run():
    state=json.loads(DATA.read_text()) if DATA.exists() else {'records':[],'runs':[]}
    records=state.get('records',[]);runs=state.get('runs',[])
    if state.get('start_date'):records=[r for r in records if in_scope(r.get('date'))]
    for name in ('data','posts','notices','history'):(SITE/name).mkdir(parents=True,exist_ok=True)
    by_id=defaultdict(list)
    for r in records:by_id[r['id']].append(r)
    latest=[items[0] for items in by_id.values()]
    for item in latest:item['publication_date']=date_key(item.get('date'))
    atomic_write(SITE/'data/records.json',merge_latest(latest))
    atomic_write(SITE/'data/runs.json',runs)
    historical_days=defaultdict(list)
    for item in merge_latest(latest):
        key=date_key(item.get('date'))
        if key and key>=START_DATE:historical_days[key].append(item)
    date_index=[]
    for key,items in sorted(historical_days.items(),reverse=True):
        content=f'<p class="lead">원자료 기준일 {e(key)} · {len(items)}건</p><p>과거 자료를 원래 날짜별로 모았습니다. 실제 수집·최초확인 시각은 각 기록에 표시합니다.</p>'+''.join(item_block(r) for r in items)
        (SITE/'history'/f'{key}.html').write_text(page(key+' 원자료 기록',content))
        date_index.append({'date':key,'count':len(items),'url':f'history/{key}.html'})
    atomic_write(SITE/'data/dates.json',date_index)
    atomic_write(SITE/'data/coverage.json',{'start_date':START_DATE,'backfill':state.get('backfill'),'api_services':8,'partner_boards':5})
    for ident,items in by_id.items():
        related=explicit_related(items[0],latest)
        links=''.join(f'<p><a href="{e(r["id"])}.html">{e(r.get("stage"))} · {e(r.get("service"))} · {e(r.get("title"))}</a></p>' for r in related)
        content=''.join(item_block(r,True) for r in items)+(('<h2>공고번호·명시 참조번호로 연결된 기록</h2>'+links) if links else '')
        (SITE/'notices'/f'{ident}.html').write_text(page(items[0]['title'],content))
    days=defaultdict(list)
    for r in runs:days[r['date']].append(r)
    for date,checks in days.items():
        entries=[r for r in records if r.get('observed_at',r.get('first_seen','')).startswith(date)]
        historical_count=sum(bool(r.get('historical_import')) for r in entries)
        summary=(f'과거 자료 추가 {historical_count}건 · 그 외 신규·변경 {len(entries)-historical_count}건' if historical_count else f'새로 확인된 사항 {len(entries)}건') if entries else '신규 공고 없음' if checks[0].get('complete') else '조회 불완전 · 신규 공고 유무를 확정할 수 없습니다'
        content=f'<p class="lead">{e(summary)}</p><p>당일 조회 {len(checks)}회</p>'+''.join(item_block(r) for r in entries)
        for check in checks:
            content+=f'<h2>조회 상태 · {e(check.get("checked_at"))}</h2><div class="table-wrap"><table><thead><tr><th>대상</th><th>상태</th><th>내용</th></tr></thead><tbody>'
            for s in check.get('statuses',[]):content+=f'<tr><td>{e(s["service"])} · {e(s["category"])}</td><td>{e(s["status"])}</td><td>{e(s["detail"])}</td></tr>'
            content+='</tbody></table></div>'
        (SITE/'posts'/f'{date}.html').write_text(page(date+' 공고·조회 기록',content))
    print(f'rendered {len(days)} daily pages and {len(by_id)} notice pages')
if __name__=='__main__':run()
