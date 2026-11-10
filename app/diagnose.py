import os,json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import requests
from app.collector import KST,parse_page,FeedError

def run():
    key=os.environ['DATA_GO_KR_KEY'];now=datetime.now(KST);start=now-timedelta(days=7)
    cases=[(100,page) for page in range(1,70)]
    def check(case):
        size,page=case;p={'serviceKey':key,'pageNo':page,'numOfRows':size,'openDtmStart':start.strftime('%Y%m%d'),'openDtmEnd':now.strftime('%Y%m%d')}
        r=requests.get('https://apis.data.go.kr/B552555/OpenTenderopenList/getOpenTenderopenList',params=p,timeout=30)
        out={'page':page,'requested_rows':size,'http':r.status_code}
        try:
            rows,total=parse_page(r.text);out.update(rows=len(rows),total=total,samples=[{k:v for k,v in row.items() if k in ('bidNum','bidDegree','bidnmKor','openDtm')} for row in rows[-1:]])
        except FeedError as ex:out.update(error=ex.code,body=r.text.replace(key,'[REDACTED]')[:800])
        print(json.dumps(out,ensure_ascii=False),flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(check,cases))
if __name__=='__main__':run()
