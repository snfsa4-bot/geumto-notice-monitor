"""Bounded, sanitized official-API diagnostics using an Actions secret."""
import json
import os
from datetime import datetime,timedelta
from pathlib import Path
import requests
from concurrent.futures import ThreadPoolExecutor
from app.collector import SOURCES,KST,parse_page,request_params,FeedError,pick,atomic_write

def run():
    now=datetime.now(KST);key=os.environ.get('DATA_GO_KR_KEY','').strip()
    results=[]
    if not key: raise SystemExit('DATA_GO_KR_KEY is not configured')
    def check(source):
        service,category,url,stage=source
        start=now-timedelta(days=7)
        if service=='LH 전자조달' and stage=='계약':
            params={'serviceKey':key,'pageNo':1,'numOfRows':2,'contractDtStart':start.strftime('%Y%m%d'),'contractDtEnd':now.strftime('%Y%m%d'),'bidNum':''}
        else:
            params=request_params(source,key,start,now);params['numOfRows']=2
        result={'service':service,'category':category,'endpoint':url,'period_days':7,'checked_at':now.isoformat(timespec='seconds')}
        try:
            response=requests.get(url,params=params,timeout=(10,30))
            result['http_status']=response.status_code
            rows,total=parse_page(response.text)
            if response.status_code!=200: raise FeedError('http_'+str(response.status_code),'HTTP error')
            result.update(status='success',total_count=total,samples=[{k:str(row[k]) for k in ('bidNtceNo','bidNtceOrd','bidNum','bidDegree','bfSpecRgstNo','untyCntrctNo','bidNtceNm','prdctClsfcNoNm','cnstwkNm','cntrctNm','ctrctNm','bidnmKor','bsnsNm','bidNtceDt','rcptDt','openDtm','cntrctCnclsDate','ctrctCntrctgDt') if row.get(k)} for row in rows])
        except FeedError as ex:result.update(status='error',code=ex.code,detail=str(ex))
        except requests.RequestException:result.update(status='error',code='network_error')
        except (ValueError,TypeError):result.update(status='error',code='schema_error')
        print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(check,SOURCES))
    atomic_write(Path('diagnostics/api-probe.json'),results)
if __name__=='__main__':run()
