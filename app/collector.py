"""Official-schema based collection. Live validation is a separate deployment gate."""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo
import requests
from app.dates import START_DATE,date_key,in_scope,windows
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.getLogger("urllib3").setLevel(logging.CRITICAL)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
KST = ZoneInfo('Asia/Seoul')
CONTRACTS = json.loads((ROOT / 'config/api-contracts.json').read_text())
SOURCES = []
for dataset, prefix, stage in [
    ('15129394','getBidPblancListInfo','입찰공고'),
    ('15129437','getPublicPrcureThngInfo','사전규격'),
    ('15129397','getOpengResultListInfo','개찰결과'),
    ('15129397','getScsbidListSttus','낙찰결과'),
    ('15129427','getCntrctInfoList','계약')]:
    for kind, label in [('Thng','물품'),('Cnstwk','공사'),('Servc','용역')]:
        operation = f'{prefix}{kind}PPSSrch' + ('02' if dataset == '15129394' else '')
        SOURCES.append(('나라장터', f'{stage} · {label}', 'https://' + CONTRACTS[dataset]['host'] + '/' + operation, stage))
for dataset, stage in [('15159012','입찰공고'),('15159014','개찰결과'),('15159010','계약'),('15159013','발주계획')]:
    spec = CONTRACTS[dataset]
    SOURCES.append(('LH 전자조달',stage,'https://' + spec['host'] + '/' + next(iter(spec['operations'])),stage))
STRONG_TERMS = ('성남금토','금토지구','금토2지구','금토1지구','금토동')
WEAK_TERMS = ('a-4bl','a4bl','신혼희망타운','금토')

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]

def compact(value):
    return re.sub(r'\s+', '', str(value)).lower()

def relevant(text):
    s = compact(text)
    return any(compact(t) in s for t in STRONG_TERMS) or ('성남' in s and '금토' in s)

def pick(record, *names):
    return next((str(record[n]).strip() for n in names if record.get(n) is not None and str(record[n]).strip()), '')

class FeedError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)

def parse_page(raw):
    """Reject unknown envelopes, missing codes, count mismatches, and HTML errors."""
    if raw.lstrip().startswith('<'):
        root = ET.fromstring(raw)
        def texts(name):
            return [x.text or '' for x in root.iter() if x.tag.split('}')[-1] == name]
        codes = texts('resultCode') or texts('returnReasonCode')
        if not codes:
            raise FeedError('schema_error','응답에 결과코드가 없습니다')
        code = codes[0]
        if code not in ('00','0','000'):
            raise FeedError('api_' + code, 'API 결과코드 ' + code)
        rows = [{c.tag.split('}')[-1]: c.text or '' for c in x} for x in root.iter() if x.tag.split('}')[-1] in ('item','row') and len(x)]
        count = texts('totalCount')
        if not rows and not count:
            raise FeedError('schema_error','빈 응답의 totalCount를 확인할 수 없습니다')
        total = int(count[0]) if count else None
    else:
        obj = json.loads(raw)
        envelope = obj.get('response', obj) if isinstance(obj,dict) else {}
        gateway = obj.get('OpenAPI_ServiceResponse',{}).get('cmmMsgHeader',{}) if isinstance(obj,dict) else {}
        if gateway.get('returnReasonCode'):
            error_code = str(gateway['returnReasonCode'])
            raise FeedError('api_'+error_code,'API 결과코드 '+error_code)
        header = envelope.get('header',{})
        code = str(header.get('resultCode',''))
        if not code:
            raise FeedError('schema_error','응답에 결과코드가 없습니다')
        if code not in ('00','0','000'):
            raise FeedError('api_' + code,'API 결과코드 ' + code)
        body = envelope.get('body')
        if not isinstance(body,dict):
            raise FeedError('schema_error','응답 body 형식이 다릅니다')
        total = int(body['totalCount']) if 'totalCount' in body else None
        rows = body.get('items',body.get('item'))
        if isinstance(rows,dict) and 'item' in rows:
            rows = rows['item']
        if rows in (None,'') and total == 0:
            rows = []
        if isinstance(rows,dict):
            rows = [rows]
        if not isinstance(rows,list) or any(not isinstance(x,dict) for x in rows):
            raise FeedError('schema_error','items 형식이 다릅니다')
    if total is not None and (total < 0 or (not rows and total > 0)):
        raise FeedError('incomplete','결과 건수와 본문이 일치하지 않습니다')
    return rows,total

def parse_response(body):
    return parse_page(body)[0]

def xml_to_records(body):
    return parse_response(body)

def areas_for(title):
    s=compact(title); areas=[]
    if re.search(r'a-?4bl|4블록',s): areas.append('A-4BL')
    if re.search(r'금토(?:제)?2',s): areas.append('금토2')
    if re.search(r'금토(?:제)?1',s): areas.append('금토1')
    if any(t in s for t in ('도로','기반시설','상하수','하수','교량','고속도로','조경','전기','통신')): areas.append('기반시설')
    return areas or ['지역미분류']

AMOUNTS = {'asignBdgtAmt':'배정예산','presmptPrce':'추정가격','bdgtAmt':'예산금액','fdmtlAmt':'기초금액','bssamt':'기초금액','cntrctAmt':'계약금액','ctrctAmt':'계약금액','totCntrctAmt':'총계약금액','thtmCntrctAmt':'금차계약금액','sucsfbidAmt':'최종낙찰금액','designPrc':'설계금액','expectPrc':'예정가격','odrplanDesignAmt':'설계금액','odrplanPayrrsAmt':'지급자재금액','cstrtnSumAmt':'합계금액'}

def normalize(rec, service, category, stage):
    title=pick(rec,'bidNtceNm','prdctClsfcNoNm','cnstwkNm','cntrctNm','ctrctNm','bidnmKor','bsnsNm','prcrmntNm','bidNm','title')
    if not title: return None
    context=title+' '+pick(rec,'projectNm','cnstrtsiteRgnNm','memo')
    if not relevant(context): return None
    notice_id=pick(rec,'untyCntrctNo','dcsnCntrctNo','bidNtceNo','bfSpecRgstNo','bidNum','cntrctNo','ntceNo')
    sequence=pick(rec,'bidNtceOrd','bidDegree','bidOrd')
    agency=pick(rec,'ntceInsttNm','cntrctInsttNm','orderInsttNm','dminsttNm','rlDminsttNm','revertDeptNm','orderDeptChusilnm') or ('한국토지주택공사' if service=='LH 전자조달' else '')
    date_fields={'입찰공고':('bidNtceDt','tndrbidRegDt'),'사전규격':('rcptDt','rgstDt'),'개찰결과':('openDtm','opengDt','rlOpengDt'),'낙찰결과':('fnlSucsfDate','rgstDt'),'계약':('cntrctCnclsDate','ctrctCntrctgDt','cntrctDate'),'발주계획':('aprvlDt',)}
    at=pick(rec,*date_fields.get(stage,('rgstDt',)))
    amounts=[{'label':label,'value':pick(rec,key),'field':key} for key,label in AMOUNTS.items() if pick(rec,key)]
    url=pick(rec,'bidNtceDtlUrl','bidNtceUrl','cntrctDtlInfoUrl')
    try:
        parsed=urlparse(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username: url=''
    except ValueError: url=''
    has_detail=bool(url)
    url=url or ('https://www.g2b.go.kr/' if service=='나라장터' else 'https://ebid.lh.or.kr/')
    identity=[service,stage,notice_id,sequence,pick(rec,'bidClsfcNo','rbidNo')] if notice_id else [service,stage,title,agency,at,pick(rec,'orderExpectYr'),pick(rec,'orderExpectMonth')]
    return {'id':digest(identity),'fingerprint':digest(rec),'title':title,'service':service,'category':category,'stage':stage,'base_stage':stage,'date':at,'publication_date':date_key(at),'agency':agency,'notice_id':notice_id,'sequence':sequence,'amounts':amounts,'amount':' / '.join(x['label']+' '+x['value'] for x in amounts),'url':url,'source_detail_verified':has_detail,'areas':areas_for(title),'references':{k:str(rec[k]) for k in ('bidNtceNo','bfSpecRgstNo','bidNtceNoList','ntceNo','refNo','cntrctRefNo') if rec.get(k)},'vendor':pick(rec,'bidwinnrNm','ctrctVndrNm'),'evidence':'제목 또는 사업·현장 필드에서 성남금토 연관성 확인'}

def request_params(source,key,start,end):
    service,category,url,stage=source
    p={'serviceKey':unquote(key),'pageNo':1,'numOfRows':100}
    if service=='나라장터':
        p.update(type='json',inqryDiv='1')
        if stage=='계약':
            p.update(inqryBgnDate=start.strftime('%Y%m%d'),inqryEndDate=end.strftime('%Y%m%d'))
            field='cnstwkNm' if 'Cnstwk' in url else 'cntrctNm' if 'Servc' in url else 'prdctClsfcNoNm'
            p[field]='금토'
        else:
            p.update(inqryBgnDt=start.strftime('%Y%m%d%H%M'),inqryEndDt=end.strftime('%Y%m%d%H%M'))
            p['prdctClsfcNoNm' if stage=='사전규격' else 'bidNtceNm']='금토'
    elif stage=='입찰공고': p.update(tndrbidRegDtStart=start.strftime('%Y%m%d'),tndrbidRegDtEnd=end.strftime('%Y%m%d'))
    elif stage=='개찰결과': p.update(openDtmStart=start.strftime('%Y%m%d'),openDtmEnd=end.strftime('%Y%m%d'))
    elif stage=='계약':
        # Empty bidNum verified against live API on 2026-11-10: HTTP 200, totalCount 67.
        p.update(contractDtStart=start.strftime('%Y%m%d'),contractDtEnd=end.strftime('%Y%m%d'),bidNum='')
    else: p.update(orderExpectYmStart=start.strftime('%Y%m'),orderExpectYmEnd=end.strftime('%Y%m'))
    return p

def request_page(session,url,params):
    for attempt in range(3):
        response=session.get(url,params=params,timeout=(10,45))
        try:
            rows,total=parse_page(response.text)
        except FeedError as ex:
            if ex.code in {'api_99','api_01','api_1','api_02','api_2','api_05','api_5'} and attempt<2:
                time.sleep(2**attempt)
                continue
            raise FeedError(ex.code,f"페이지 {params['pageNo']}: {ex}") from None
        if response.status_code!=200:
            raise FeedError('http_'+str(response.status_code),'HTTP '+str(response.status_code))
        return rows,total
    raise FeedError('retry_exhausted','제공기관 오류 재시도 소진')

def fetch_source(session,source,key,now,days=3,start=None,page_size=100):
    service,category,url,stage=source
    params=request_params(source,key,start or now-timedelta(days=days),now)
    rows=[];seen_pages=set();expected=None
    for request_index in range(1,1001):
        # Some LH pages fail if a page extends past totalCount. Request an exact tail.
        limit=min(page_size,expected-len(rows)) if expected is not None else page_size
        size=next(n for n in range(limit,0,-1) if len(rows)%n==0)
        params['numOfRows']=size
        page=len(rows)//size+1
        params['pageNo']=page
        try:
            batch,total=request_page(session,url,params)
        except FeedError as ex:
            if request_index==1 and page_size>100 and ex.code in {'api_10','api_99','api_08'}:
                return fetch_source(session,source,key,now,days,start,100)
            raise
        if expected is not None and total is not None and total!=expected: raise FeedError('changing_total','페이지 조회 중 전체 건수 변경: 재조회 필요')
        if total is not None: expected=total
        fingerprint=digest(batch)
        if batch and fingerprint in seen_pages: raise FeedError('repeated_page','API가 같은 페이지를 반복 반환합니다')
        seen_pages.add(fingerprint);rows.extend(batch)
        if total is not None and len(rows)>=total:
            if len(rows)!=total: raise FeedError('count_mismatch','페이지 전체 건수 불일치')
            break
        if not batch or (total is None and len(batch)<size): break
    else: raise FeedError('pagination_limit','페이지 상한 초과: 조회 불완전')
    # LH opening returns one row per bidder: group into one event, do not publish bidders as revisions.
    groups=defaultdict(list)
    for raw in rows:
        n=normalize(raw,service,category,stage)
        if n: groups[n['id']].append((n,raw))
    items=[]
    for group in groups.values():
        n=group[0][0]
        n['fingerprint']=digest(sorted((digest(r) for _,r in group)))
        evidence_fields=set(AMOUNTS)|{'bidNtceNo','bidNtceOrd','bfSpecRgstNo','bidNum','bidDegree','untyCntrctNo','bidNtceNm','prdctClsfcNoNm','cnstwkNm','cntrctNm','ctrctNm','bidnmKor','bsnsNm','bidNtceDt','tndrbidRegDt','rcptDt','fnlSucsfDate','rgstDt','openDtm','opengDt','cntrctCnclsDate','ctrctCntrctgDt','aprvlDt','orderExpectYr','orderExpectMonth'}
        n['source_fields']={k:str(group[0][1][k]) for k in sorted(evidence_fields) if group[0][1].get(k) is not None}
        if stage=='개찰결과': n['opening_note']='개찰 결과는 최종 낙찰·계약체결을 의미하지 않습니다';n['bidder_rows']=len(group)
        items.append(n)
    return items, len(rows)

def atomic_write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.state-',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def fetch_period(session,source,key,start,end):
    chunks=[(start,end)] if source[0]=='LH 전자조달' and source[3]=='발주계획' else list(windows(start,end))
    found={};raw_count=0
    for begin,stop in chunks:
        page_size=500 if source[0]=='LH 전자조달' and source[3]=='개찰결과' else 100
        items,count=fetch_source(session,source,key,stop,start=begin,page_size=page_size)
        raw_count+=count
        for item in items:found[item['id']]=item
    return list(found.values()),raw_count,len(chunks)

def ingest(items,state,seen,fresh,now,backfill=False):
    first_seen={r['id']:r.get('first_seen') for r in reversed(state.get('records',[]))}
    for item in items:
        item['publication_date']=date_key(item.get('date'))
        if not item.get('notice_id'):
            source_identity=item['id']
            legacy=next((r for r in state.get('records',[]) if not r.get('notice_id') and r.get('service')==item.get('service') and r.get('base_stage')==item.get('base_stage') and (r.get('source_identity')==source_identity or (not r.get('source_identity') and all(r.get(k)==item.get(k) for k in ('title','date','agency'))))),None)
            if legacy:
                item['id']=legacy['id']
                if not legacy.get('source_identity') and all(legacy.get(k)==item.get(k) for k in ('title','date','agency','amounts')):
                    seen[item['id']]=item['fingerprint']
                    legacy.update(item)
            item['source_identity']=source_identity
        if not in_scope(item.get('date'),now.date().isoformat()):continue
        if seen.get(item['id'])==item['fingerprint']:
            for existing in state.get('records',[]):
                if existing['id']==item['id'] and existing.get('fingerprint')==item['fingerprint']:
                    existing.update(item)
                    if existing.get('historical_import') and existing.get('publication_date')==existing.get('first_seen','')[:10]:
                        existing['historical_import']=False
                        if existing.get('change_type')=='과거자료 추가':existing['change_type']='신규'
                    if existing.get('change_type')=='변경':existing['stage']=item['stage']+' · 내용변경'
            continue
        changed=item['id'] in seen
        item['first_seen']=first_seen.get(item['id']) or now.isoformat(timespec='seconds')
        item['observed_at']=now.isoformat(timespec='seconds')
        item['event_id']=digest([item['id'],item['fingerprint']])
        is_history=bool(backfill and not changed and item['publication_date']<now.date().isoformat())
        item['historical_import']=is_history
        item['change_type']='변경' if changed else '과거자료 추가' if is_history else '신규'
        if changed:item['stage']+=' · 내용변경'
        fresh.append(item);seen[item['id']]=item['fingerprint']

def run(days=3,since=None,include_partner=False):
    now=datetime.now(KST);state_file=DATA/'state.json'
    state=json.loads(state_file.read_text()) if state_file.exists() else {'records':[],'runs':[],'fingerprints':{}}
    start=datetime.fromisoformat(since).replace(tzinfo=KST) if since else now-timedelta(days=days)
    if not since:
        last_good=next((r for r in state.get('runs',[]) if r.get('complete') and r.get('checked_at')),None)
        if last_good:start=min(start,datetime.fromisoformat(last_good['checked_at']).astimezone(KST)-timedelta(days=1))
    start=max(start,datetime.fromisoformat(START_DATE).replace(tzinfo=KST))
    if start>now:raise ValueError('조회 시작일이 오늘보다 늦습니다')
    key=os.environ.get('DATA_GO_KR_KEY','').strip()
    session=requests.Session()
    session.mount('https://',HTTPAdapter(max_retries=Retry(total=3,backoff_factor=1,status_forcelist=[429,500,502,503,504],allowed_methods=['GET'],respect_retry_after_header=True)))
    fresh=[];statuses=[];seen=dict(state.get('fingerprints',{}))
    for source in SOURCES:
        service,category,url,stage=source
        dataset=next(k for k,v in CONTRACTS.items() if url.startswith('https://'+v['host']+'/'))
        status={'dataset':dataset,'service':service,'category':category,'status':'미설정','code':'missing_key','detail':'인증키가 없어 API를 조회하지 못했습니다.','query_from':start.isoformat(),'query_to':now.isoformat()}
        if key:
            try:
                source_start=datetime.fromisoformat(START_DATE).replace(tzinfo=KST) if service=='LH 전자조달' and stage=='발주계획' else start
                status['query_from']=source_start.isoformat()
                items,raw_count,window_count=fetch_period(session,source,key,source_start,now)
                undated=sum(not date_key(r.get('date')) for r in items)
                items=[r for r in items if in_scope(r.get('date'),now.date().isoformat())]
                previous=len(fresh);ingest(items,state,seen,fresh,now,bool(since))
                status.update(status='성공',code='ok',detail=f'기간분할 {window_count}회 / 원자료 {raw_count}행 / 기간·지역 일치 {len(items)}건 / 추가·변경 {len(fresh)-previous}건',raw_count=raw_count,matched_count=len(items))
                if undated:status.update(status='조회 불완전',code='date_unverified',detail=status['detail']+f' / 날짜 미확인 {undated}건 제외·검토 필요')
            except FeedError as ex:status.update(status='조회 실패',code=ex.code,detail=str(ex))
            except requests.RequestException:status.update(status='조회 실패',code='network_error',detail='통신 오류 또는 재시도 소진. 인증키를 포함한 요청 URL은 기록하지 않습니다.')
            except (ValueError,ET.ParseError,KeyError,TypeError):status.update(status='조회 실패',code='schema_error',detail='응답 형식 또는 필드가 명세와 다릅니다. 검토 필요.')
        status['checked_at']=datetime.now(KST).isoformat(timespec='seconds');statuses.append(status)
        print(json.dumps({'source':category,'service':service,'status':status['status'],'code':status['code']},ensure_ascii=False),flush=True)
    if include_partner:
        from app.partner import collect
        partner_items,partner_statuses,_=collect(session,now.date().isoformat())
        ingest(partner_items,state,seen,fresh,now,bool(since));statuses.extend(partner_statuses)
    stamp=datetime.now(KST).isoformat(timespec='seconds')
    datasets=set(CONTRACTS)|({'partner'} if include_partner else set())
    new_run={'date':now.strftime('%Y-%m-%d'),'started_at':now.isoformat(timespec='seconds'),'checked_at':stamp,'lookback_days':days,'query_from':start.isoformat(),'query_to':now.isoformat(),'backfill':bool(since),'statuses':statuses,'new_ids':[r['id'] for r in fresh],'new_event_ids':[r['event_id'] for r in fresh],'successful_sources':sum(s['status']=='성공' for s in statuses),'total_sources':len(statuses),'new_count':len(fresh),'historical_count':sum(r.get('historical_import',False) for r in fresh),'complete':all(s['status']=='성공' for s in statuses)}
    new_run['successful_services']=sum(all(s['status']=='성공' for s in statuses if s['dataset']==dataset) for dataset in datasets)
    new_run['total_services']=len(datasets)
    state.update(start_date=START_DATE,fingerprints=seen,records=fresh+state.get('records',[]),runs=[new_run]+state.get('runs',[]))
    if since:state['backfill']={'from':start.date().isoformat(),'to':now.date().isoformat(),'checked_at':stamp,'complete':new_run['complete']}
    atomic_write(state_file,state)
    print(json.dumps({k:new_run[k] for k in ('successful_sources','total_sources','new_count','complete')},ensure_ascii=False))
    if os.environ.get('REQUIRE_COMPLETE_RUN')=='1' and not new_run['complete']:return 2
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--days',type=int,default=3,choices=range(1,32));parser.add_argument('--since',type=str);parser.add_argument('--partner',action='store_true');args=parser.parse_args()
    sys.exit(run(args.days,args.since,args.partner))
