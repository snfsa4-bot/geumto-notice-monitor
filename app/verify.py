"""Compare stored notices with fresh official fields, without using normalize()."""
import json,os
from datetime import datetime,timedelta
from pathlib import Path
import requests
from app.collector import ROOT,KST,SOURCES,request_params,parse_page,atomic_write
TITLE_FIELDS=('bidNtceNm','prdctClsfcNoNm','cnstwkNm','cntrctNm','ctrctNm','bidnmKor','bsnsNm')
NUMBER_FIELDS=('untyCntrctNo','dcsnCntrctNo','bidNtceNo','bfSpecRgstNo','bidNum','cntrctNo','ntceNo')
DATE_FIELDS={'입찰공고':('bidNtceDt','tndrbidRegDt'),'사전규격':('rcptDt','rgstDt'),'개찰결과':('openDtm','opengDt','rlOpengDt'),'낙찰결과':('fnlSucsfDate','rgstDt'),'계약':('cntrctCnclsDate','ctrctCntrctgDt','cntrctDate'),'발주계획':('aprvlDt',)}
def first(row,names):return next((str(row[k]).strip() for k in names if row.get(k) is not None and str(row[k]).strip()),'')
def compare(notice,raw):
    checks={'title':notice['title']==first(raw,TITLE_FIELDS),'number':notice['notice_id']==first(raw,NUMBER_FIELDS),'date':notice['date']==first(raw,DATE_FIELDS[notice['base_stage']]),'amounts':all(str(raw.get(a['field'],'')).strip()==a['value'] for a in notice.get('amounts',[]))}
    return checks

def run():
    key=os.environ.get('DATA_GO_KR_KEY','').strip()
    if not key:raise SystemExit('Missing DATA_GO_KR_KEY')
    now=datetime.now(KST);since=(now-timedelta(days=7)).isoformat()
    state=json.loads((ROOT/'data/state.json').read_text());latest={}
    for n in state['records']:
        if n['id'] not in latest and n.get('observed_at','')>=since:latest[n['id']]=n
    results=[];cache={}
    with requests.Session() as session:
        for notice in latest.values():
            source=next(s for s in SOURCES if s[0]==notice['service'] and s[1]==notice['category'])
            if source not in cache:
                params=request_params(source,key,now-timedelta(days=7),now);all_rows=[];expected=None
                for request_index in range(1,1001):
                    limit=min(100,expected-len(all_rows)) if expected is not None else 100
                    size=next(n for n in range(limit,0,-1) if len(all_rows)%n==0)
                    params['numOfRows']=size
                    params['pageNo']=len(all_rows)//size+1
                    response=session.get(source[2],params=params,timeout=(10,45));response.raise_for_status()
                    rows,total=parse_page(response.text);all_rows.extend(rows);expected=total
                    if (total is not None and len(all_rows)>=total) or not rows:break
                else:raise RuntimeError('Verification pagination incomplete')
                cache[source]=all_rows
            candidates=[r for r in cache[source] if first(r,TITLE_FIELDS)==notice['title'] and first(r,NUMBER_FIELDS)==notice['notice_id']]
            checks=compare(notice,candidates[0]) if candidates else {'record_found':False}
            result={'id':notice['id'],'notice_number':notice['notice_id'] or 'API 미제공','title':notice['title'],'stage':notice['base_stage'],'checks':checks,'passed':all(checks.values())}
            results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    report={'checked_at':now.isoformat(timespec='seconds'),'method':'Fresh official API fields compared independently with stored titles, identifiers, dates and typed amount fields','results':results,'passed':bool(results) and all(r['passed'] for r in results)}
    atomic_write(ROOT/'data/verification.json',report)
    if not report['passed']:raise SystemExit(2)
if __name__=='__main__':run()
