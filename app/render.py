"""Render latest notices, immutable revision history, and daily query status."""
import html
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse
from app.collector import atomic_write
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/state.json'
SITE=ROOT/'site'
def e(value): return html.escape(str(value or ''),quote=True)
def page(title,content):
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} | 금토 공고기록</title><link rel="stylesheet" href="../assets/style.css"></head><body><div class="shell"><header class="topbar"><a class="brand" href="../index.html">금토 공고기록</a><a href="../index.html">전체 기록</a></header><main><h1>{e(title)}</h1>{content}</main><footer>성남금토 공공조달 모니터링 · 비공식 주민 정보 서비스</footer></div></body></html>'
def item_block(r,detail=False):
    amounts=' / '.join(x['label']+' '+x['value']+'원' for x in r.get('amounts',[])) or '금액 미확인'
    text=f'<article class="post-item"><p>{e(r.get("service"))} · {e(r.get("stage"))}</p><h2>{e(r.get("title"))}</h2><p>공고번호 {e(r.get("notice_id") or "미제공")} · 차수 {e(r.get("sequence") or "미제공")}</p><p>기관 {e(r.get("agency"))} · 업체 {e(r.get("vendor") or "미확인")}</p><p>{e(amounts)}</p><p>원자료 기준일 {e(r.get("date") or "미제공")}<br>최초 확인 {e(r.get("first_seen"))}<br>이번 확인 {e(r.get("observed_at",r.get("first_seen")))}</p>'
    u=r.get('url','')
    if urlparse(u).scheme in ('https','http'):
        label='원문 확인' if r.get('source_detail_verified') else '공식 사이트에서 공고번호 검색'
        text+=f'<a href="{e(u)}" target="_blank" rel="noopener noreferrer">{label} ↗</a>'
    if not detail: text+=f' <a href="../notices/{e(r["id"])}.html">상세 기록</a>'
    if r.get('opening_note'):text+=f'<p>{e(r["opening_note"])}</p>'
    return text+'</article>'
def run():
    state=json.loads(DATA.read_text()) if DATA.exists() else {'records':[],'runs':[]}
    records=state.get('records',[]);runs=state.get('runs',[])
    for name in ('data','posts','notices'):(SITE/name).mkdir(parents=True,exist_ok=True)
    by_id=defaultdict(list)
    for r in records:by_id[r['id']].append(r)
    atomic_write(SITE/'data/records.json',[items[0] for items in by_id.values()])
    atomic_write(SITE/'data/runs.json',runs)
    for ident,items in by_id.items():
        (SITE/'notices'/f'{ident}.html').write_text(page(items[0]['title'],''.join(item_block(r,True) for r in items)))
    days=defaultdict(list)
    for r in runs:days[r['date']].append(r)
    for date,checks in days.items():
        entries=[r for r in records if r.get('observed_at',r.get('first_seen','')).startswith(date)]
        summary=f'새로 확인된 사항 {len(entries)}건' if entries else '신규 공고 없음' if checks[0].get('complete') else '조회 불완전 · 신규 공고 유무를 확정할 수 없습니다'
        content=f'<p class="lead">{e(summary)}</p><p>당일 조회 {len(checks)}회</p>'+''.join(item_block(r) for r in entries)
        for check in checks:
            content+=f'<h2>조회 상태 · {e(check.get("checked_at"))}</h2><div class="table-wrap"><table><thead><tr><th>대상</th><th>상태</th><th>내용</th></tr></thead><tbody>'
            for s in check.get('statuses',[]):content+=f'<tr><td>{e(s["service"])} · {e(s["category"])}</td><td>{e(s["status"])}</td><td>{e(s["detail"])}</td></tr>'
            content+='</tbody></table></div>'
        (SITE/'posts'/f'{date}.html').write_text(page(date+' 공고·조회 기록',content))
    print(f'rendered {len(days)} daily pages and {len(by_id)} notice pages')
if __name__=='__main__':run()
