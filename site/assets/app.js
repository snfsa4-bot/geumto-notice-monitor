'use strict';
const $ = id => document.getElementById(id);
const fmt = s => {if(!s)return '미확인';const raw=String(s);return /^\d{8}$/.test(raw)?`${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)}`:raw.replace('T',' ').slice(0,16);};
const safeURL = u => { try { const url = new URL(u); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; } };
let allRecords = [];
let filter = '전체';
function areasOf(r) { return r.areas || ['지역미분류']; }
function node(tag, props={}, text='') {
  const n=document.createElement(tag); Object.entries(props).forEach(([k,v]) => { if(k==='className') n.className=v; else n.setAttribute(k,v); }); if (text) n.textContent=text; return n;
}
function empty(title,detail){const el=node('div',{className:'empty-state'});el.append(node('span',{className:'empty-symbol'},'↗'),node('h3',{},title),node('p',{},detail));return el;}
function renderRecords(){
  const q=$('query').value.trim().toLowerCase();const stage=$('stage').value;const from=$('from').value;const to=$('to').value;
  const matches=allRecords.filter(r=>(!stage||(r.base_stage||r.stage)===stage)&&(!from||(r.publication_date||'')>=from)&&(!to||(r.publication_date||'')<=to)&&(filter==='전체'||areasOf(r).includes(filter)) && [r.title,r.notice_id,r.agency,r.vendor,r.stage,r.category].join(' ').toLowerCase().includes(q));
  $('record-list').replaceChildren();
  if(!matches.length){$('record-list').append(empty(allRecords.length?'검색 결과가 없습니다':'아직 확인된 공고 데이터가 없습니다',allRecords.length?'다른 검색어나 지역을 선택해 보세요.':'API 연결 후 실제 확인된 공고만 여기에 자동으로 올라옵니다.'));return;}
  for(const r of matches){
    const card=node('article',{className:'record-card'}), top=node('div',{className:'record-top'});
    top.append(node('span',{className:'pill'},r.stage||'공고'),node('span',{},r.service||'출처 미확인'),node('span',{},fmt(r.date)));
    card.append(top,node('h3',{},r.title||'제목 없음'));if(r.historical_import)card.append(node('span',{className:'pill'},'과거 자료 추가'));
    const info=node('div',{className:'record-info'}); for (const x of [`공고번호 ${r.notice_id||'미확인'}`,`금액 ${r.amounts?.length?r.amounts.map(a=>`${a.label} ${Number(a.value.replaceAll(',','')).toLocaleString('ko-KR')}원`).join(' / '):'미확인'}`,r.agency||'기관 미확인']) info.append(node('span',{},x));card.append(info);if(r.sources?.length>1){card.append(node('p',{},`동일 공고 출처 ${r.sources.length}개 · 상세 기록에서 비교`));}card.append(node('a',{href:`notices/${encodeURIComponent(r.id)}.html`},'상세·변경 이력 보기'));
    const u=safeURL(r.url);if(u){const a=node('a',{href:u,target:'_blank',rel:'noopener noreferrer',className:'record-open'},r.source_detail_verified?'원문 바로가기 ↗':'공식 사이트 검색 ↗');card.append(a);if(!r.source_detail_verified)card.append(node('span',{className:'unverified'},'공식 목록 링크 · 상세주소 미확인'));}
    $('record-list').append(card);
  }
}
function renderRuns(runs){
  const list=$('archive-list');list.replaceChildren();
  if(!runs.length){list.append(node('p',{className:'archive-placeholder'},'아직 게시된 일일 기록이 없습니다.'));return;}
  for(const r of [...new Map([...runs].reverse().map(r=>[r.date,r])).values()].reverse().slice(0,60)){
    const anchor=node('a',{className:'archive-row',href:`posts/${r.date}.html`});
    const wrap=node('span',{className:'archive-label'});const imported=runs.filter(x=>x.date===r.date).reduce((n,x)=>n+(x.historical_count||0),0);wrap.append(node('strong',{},r.date),node('span',{className:'archive-count'},imported ? `과거 자료 추가 ${imported}건 · 조회 ${r.complete?'정상':'불완전'}` : r.complete ? (runs.filter(x=>x.date===r.date).reduce((n,x)=>n+x.new_count,0) ? `신규·변경 ${runs.filter(x=>x.date===r.date).reduce((n,x)=>n+x.new_count,0)}건` : '신규 공고 없음') : `조회 불완전 · 확인 ${r.new_count}건`));
    anchor.append(wrap,node('span',{},'기록 확인 ↗'));list.append(anchor);
  }
}
function renderStatus(run){
  const body=$('status-body');body.replaceChildren();
  if(!run){const r=node('tr');for(const text of ['나라장터 · LH','연동 준비 중','첫 정상 수집 전'])r.append(node('td',{},text));body.append(r);return;}
  for(const s of run.statuses){const tr=node('tr');tr.append(node('td',{},`${s.service} · ${s.category}`));
    const td=node('td');td.append(node('span',{className:s.status==='성공'?'status-ok':s.status==='조회 실패'?'status-error':'status-wait'},s.status));tr.append(td,node('td',{},s.detail||''));body.append(tr);}
}
async function main(){
  try{
    const [r1,r2]=await Promise.all([fetch('data/records.json',{cache:'no-cache'}),fetch('data/runs.json',{cache:'no-cache'})]);
    if(!r1.ok||!r2.ok)throw Error('파일 로딩 실패');
    const [records,runs]=await Promise.all([r1.json(),r2.json()]);
    allRecords=records||[];allRecords.sort((a,b)=>(b.publication_date||'').localeCompare(a.publication_date||''));
    const last=runs[0]; const stale=last&&Date.now()-Date.parse(last.checked_at)>27*3600000; const lastGood=runs.find(r=>r.complete);$('metric-total').textContent=allRecords.length.toLocaleString('ko-KR');
    const since=Date.now()-7*86400000;
    $('metric-week').textContent=allRecords.filter(r=>Date.parse(r.publication_date||0)>=since).length.toLocaleString('ko-KR');
    $('metric-updated').textContent=lastGood?fmt(lastGood.checked_at):'정상 조회 전';
    $('sync-status').textContent=last?(stale?'예약 조회 지연 · 최신 상태 확인 필요':last.complete?'정상 조회':`조회 불완전 (${last.successful_services??last.successful_sources}/${last.total_services??last.total_sources})`):'연동 준비 중';
    renderRuns(runs||[]);renderStatus(last);renderRecords();
    const datesResponse=await fetch('data/dates.json',{cache:'no-cache'});if(!datesResponse.ok)throw Error('날짜별 기록 읽기 실패');
    const coverageResponse=await fetch('data/coverage.json',{cache:'no-cache'});if(coverageResponse.ok){const coverage=await coverageResponse.json();$('coverage-status').textContent=coverage.backfill?`수집 범위 ${coverage.start_date} ~ ${coverage.backfill.to} · 과거자료 조회 ${coverage.backfill.complete?'완료':'불완전, 수집 현황 확인 필요'} · API 8종 + 공개 게시판 5곳`:`수집 기준 ${coverage.start_date} 이후 · 과거자료 수집 상태 확인 중`;}
    const dates=await datesResponse.json();$('history-list').replaceChildren();for(const day of dates){const a=node('a',{className:'archive-row',href:day.url});a.append(node('strong',{},day.date),node('span',{},`${day.count}건 · 원자료 날짜`));$('history-list').append(a);}if(!dates.length)$('history-list').append(node('p',{},'기간 내 확인된 자료가 없습니다. 수집 현황을 함께 확인해 주세요.'));
  }catch(error){$('sync-status').textContent='데이터 로딩 실패';$('record-list').replaceChildren(empty('데이터를 읽지 못했습니다','잠시 뒤 다시 시도해 주세요. 문제가 계속되면 수집 작업의 실행 기록을 확인해 주세요.'));}
}
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');filter=b.dataset.filter;renderRecords();}));
$('query').addEventListener('input',renderRecords);
['stage','from','to'].forEach(id=>$(id).addEventListener('change',renderRecords));
main();
