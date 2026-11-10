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
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo
import requests
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
    at=pick(rec,'bidNtceDt','rcptDt','fnlSucsfDate','rlOpengDt','openDtm','opengDt','cntrctCnclsDate','ctrctCntrctgDt','aprvlDt','rgstDt')
    amounts=[{'label':label,'value':pick(rec,key),'field':key} for key,label in AMOUNTS.items() if pick(rec,key)]
    url=pick(rec,'bidNtceDtlUrl','bidNtceUrl','cntrctDtlInfoUrl')
    try:
        parsed=urlparse(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username: url=''
    except ValueError: url=''
    has_detail=bool(url)
    url=url or ('https://www.g2b.go.kr/' if service=='나라장터' else 'https://ebid.lh.or.kr/')
    identity=[service,stage,notice_id or title,sequence, pick(rec,'bidClsfcNo','rbidNo')]
    return {'id':digest(identity),'fingerprint':digest(rec),'title':title,'service':service,'category':category,'stage':stage,'base_stage':stage,'date':at,'agency':agency,'notice_id':notice_id,'sequence':sequence,'amounts':amounts,'amount':' / '.join(x['label']+' '+x['value'] for x in amounts),'url':url,'source_detail_verified':has_detail,'areas':areas_for(title),'references':{k:str(rec[k]) for k in ('bidNtceNo','bfSpecRgstNo','bidNtceNoList','ntceNo','refNo','cntrctRefNo') if rec.get(k)},'vendor':pick(rec,'bidwinnrNm','ctrctVndrNm'),'evidence':'제목 또는 사업·현장 필드에서 성남금토 연관성 확인'}

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

def fetch_source(session,source,key,now,days=3):
    service,category,url,stage=source
    params=request_params(source,key,now-timedelta(days=days),now)
    rows=[];seen_pages=set();expected=None
    for page in range(1,1001):
        params['pageNo']=page
        response=session.get(url,params=params,timeout=(10,45))
        if response.status_code!=200:
            try:
                parse_page(response.text)
            except FeedError as ex:
                if ex.code.startswith('api_'):
                    raise FeedError(ex.code, f'HTTP {response.status_code} · {ex}') from None
            except (ValueError, ET.ParseError, TypeError):
                pass
            raise FeedError('http_'+str(response.status_code),'HTTP '+str(response.status_code))
        batch,total=parse_page(response.text)
        if expected is not None and total is not None and total!=expected: raise FeedError('changing_total','페이지 조회 중 전체 건수 변경: 재조회 필요')
        if total is not None: expected=total
        fingerprint=digest(batch)
        if batch and fingerprint in seen_pages: raise FeedError('repeated_page','API가 같은 페이지를 반복 반환합니다')
        seen_pages.add(fingerprint);rows.extend(batch)
        if total is not None and len(rows)>=total:
            if len(rows)!=total: raise FeedError('count_mismatch','페이지 전체 건수 불일치')
            break
        if not batch or (total is None and len(batch)<100): break
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

def run(days=3):
    now=datetime.now(KST);state_file=DATA/'state.json'
    state=json.loads(state_file.read_text()) if state_file.exists() else {'records':[],'runs':[],'fingerprints':{}}
    key=os.environ.get('DATA_GO_KR_KEY','').strip()
    session=requests.Session()
    session.mount('https://',HTTPAdapter(max_retries=Retry(total=3,backoff_factor=1,status_forcelist=[429,500,502,503,504],allowed_methods=['GET'],respect_retry_after_header=True)))
    fresh=[];statuses=[];seen=dict(state.get('fingerprints',{}));first_seen={r['id']:r.get('first_seen') for r in reversed(state.get('records',[]))}
    for source in SOURCES:
        service,category,url,stage=source
        dataset=next(k for k,v in CONTRACTS.items() if url.startswith('https://'+v['host']+'/'))
        status={'dataset':dataset,'service':service,'category':category,'status':'미설정','code':'missing_key','detail':'인증키가 없어 API를 조회하지 못했습니다.','checked_at':now.isoformat(timespec='seconds')}
        if key:
            try:
                items,raw_count=fetch_source(session,source,key,now,days)
                count=0
                for item in items:
                    if seen.get(item['id'])==item['fingerprint']: continue
                    changed=item['id'] in seen
                    item['first_seen']=first_seen.get(item['id']) or now.isoformat(timespec='seconds')
                    item['observed_at']=now.isoformat(timespec='seconds')
                    item['event_id']=digest([item['id'],item['fingerprint']])
                    item['change_type']='변경' if changed else '신규'
                    if changed: item['stage']+=' · 내용변경'
                    fresh.append(item);seen[item['id']]=item['fingerprint'];count+=1
                status.update(status='성공',code='ok',detail=f'원자료 {raw_count}건 / 지역일치 {len(items)}건 / 신규·변경 {count}건',raw_count=raw_count,matched_count=len(items))
            except FeedError as ex: status.update(status='조회 실패',code=ex.code,detail=str(ex))
            except requests.RequestException: status.update(status='조회 실패',code='network_error',detail='통신 오류 또는 재시도 소진. 인증키를 포함한 요청 URL은 기록하지 않습니다.')
            except (ValueError,ET.ParseError,KeyError,TypeError): status.update(status='조회 실패',code='schema_error',detail='응답 형식 또는 필드가 명세와 다릅니다. 검토 필요.')
        statuses.append(status)
        print(json.dumps({'source':category,'service':service,'status':status['status'],'code':status['code']},ensure_ascii=False),flush=True)
    stamp=now.isoformat(timespec='seconds')
    new_run={'date':now.strftime('%Y-%m-%d'),'checked_at':stamp,'lookback_days':days,'statuses':statuses,'new_ids':[r['id'] for r in fresh],'new_event_ids':[r['event_id'] for r in fresh],'successful_sources':sum(s['status']=='성공' for s in statuses),'total_sources':len(statuses),'new_count':len(fresh),'complete':all(s['status']=='성공' for s in statuses)}
    new_run['successful_services']=sum(all(s['status']=='성공' for s in statuses if s['dataset']==dataset) for dataset in CONTRACTS)
    new_run['total_services']=len(CONTRACTS)
    state.update(fingerprints=seen,records=fresh+state.get('records',[]),runs=[new_run]+state.get('runs',[]))
    atomic_write(state_file,state)
    print(json.dumps({k:new_run[k] for k in ('successful_sources','total_sources','new_count','complete')},ensure_ascii=False))
    if os.environ.get('REQUIRE_COMPLETE_RUN')=='1' and not new_run['complete']: return 2
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--days',type=int,default=3,choices=range(1,32));args=parser.parse_args()
    sys.exit(run(args.days))
