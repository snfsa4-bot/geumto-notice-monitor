"""Read-only public LH Partner Mall boards, bounded to dated Geumto evidence."""
from __future__ import annotations
import re,time,hashlib
from urllib.parse import urljoin,urlparse,unquote
from urllib.robotparser import RobotFileParser
from datetime import datetime
from bs4 import BeautifulSoup
from app.collector import FeedError,digest,relevant,areas_for,KST
from app.dates import START_DATE,date_key
from app.attachments import extract,LIMIT
BASE='https://partner.lh.or.kr'
SERVICE='LH 기술혁신파트너몰'
BOARDS=[
 ('공모·심의 계획','/deliberate/deliberate.asp',{'searchItem':'','searchKeyword':'금토'},'공모'),
 ('선정심의 결과','/deliberate/deliberate_innerList.asp',{'searchField':'rr_contract','searchKeyWord':'금토'},'선정심의 결과'),
 ('특정공법·자재 반영현황','/technology/tech_app_list.asp',{'searchItem':'or_place','searchKeyword':'금토'},'기술 반영'),
 ('공지사항','/community/notice_list.asp',{},'공지'),
 ('심의위원 선정결과','/community/r_list.asp',{},'심의위원 선정'),
]

def soup_of(raw):
    soup=BeautifulSoup(raw,'html.parser')
    for tag in soup(['script','style','header','footer','aside','nav']):tag.decompose()
    return soup

def text_of(node):return node.get_text(' ',strip=True) if node else ''

def get_link(anchor,base):
    href=anchor.get('href','')
    if href and not href.startswith(('javascript:','#')):return urljoin(base,href)
    onclick=anchor.get('onclick','')
    match=re.search(r"(?:submitParam|goHref)\('([^']+)'",onclick)
    if not match:return ''
    target=urljoin(base,match[1])
    # Only parameters actually declared by the site's visible link handler.
    idx=re.search(r"['\"]idx=(\d+)['\"]",onclick)
    if idx and 'idx=' not in target:target+=('&' if '?' in target else '?')+'idx='+idx[1]
    return target

class PublicClient:
    def __init__(self,session):
        self.session=session;self.count=0;self.attachment_count=0
        self.robot=RobotFileParser();r=session.get(BASE+'/robots.txt',timeout=(10,30));r.raise_for_status()
        self.robot.parse(r.text.splitlines())
    def request(self,url,data=None,binary=False):
        if urlparse(url).hostname!='partner.lh.or.kr':raise FeedError('unsafe_link','파트너몰 외부 주소는 조회하지 않습니다')
        if not self.robot.can_fetch('GeumtoNoticeMonitor',url):raise FeedError('robots_disallowed','자동 조회 제외 경로')
        time.sleep(.25)
        for attempt in range(3):
            r=self.session.request('POST' if data is not None else 'GET',url,data=data,timeout=(10,35),headers={'User-Agent':'GeumtoNoticeMonitor/1.0 (+https://snfsa4-bot.github.io/geumto-notice-monitor/)'},allow_redirects=False,stream=True)
            if r.status_code in (429,500,502,503,504) and attempt<2:r.close();time.sleep(2**attempt);continue
            r.raise_for_status()
            if 300<=r.status_code<400:raise FeedError('redirect','공개 페이지가 다른 주소나 로그인으로 이동합니다')
            chunks=[];size=0
            for part in r.iter_content(65536):
                size+=len(part)
                if size>LIMIT:r.close();raise FeedError('size_limit','공개 자료 크기 제한 초과')
                chunks.append(part)
            data_bytes=b''.join(chunks);r.close();self.count+=1
            if binary:return data_bytes,r.headers
            raw=data_bytes.decode('utf-8',errors='replace')
            if 'location.href' in raw and 'login.asp' in raw and len(raw)<2000:raise FeedError('login_required','로그인이 필요한 자료')
            return raw
        raise FeedError('network_error','파트너몰 재시도 소진')

def parse_rows(raw,kind,path):
    soup=soup_of(raw);rows=[]
    if kind=='공모':
        for a in soup.select('[onclick]'):
            match=re.search(r'openView\((\d+)\)',a.get('onclick',''))
            if not match:continue
            tr=a.find_parent('tr');tds=tr.find_all('td',recursive=False)
            if len(tds)<5:raise FeedError('partner_schema','공모 목록 열 변경')
            rows.append({'key':match[1],'title':text_of(tds[0]),'list_date':date_key(text_of(tds[2])),'list_date_label':'공모 시작일','list_text':text_of(tr),'detail':BASE+'/deliberate/deliberate_detail.asp','post':{'re_idx':match[1]}})
        if '자재공법 선정심의 계획 및 공모' not in text_of(soup):raise FeedError('partner_schema','공모 목록 확인 실패')
    elif kind=='선정심의 결과':
        for a in soup.select('[onclick]'):
            match=re.search(r'openResultView\((\d+)\)',a.get('onclick',''))
            if not match:continue
            tr=a.find_parent('tr');tds=tr.find_all('td',recursive=False)
            if len(tds)<5:raise FeedError('partner_schema','심의 결과 목록 열 변경')
            rows.append({'key':match[1],'title':text_of(tds[0])+' · '+text_of(tds[3]),'list_date':date_key(text_of(tds[2])),'list_date_label':'심의일','list_text':text_of(tr),'vendor':text_of(tds[4]),'detail':BASE+'/deliberate/deliberate_innerView.asp','post':{'rr_idx':match[1]}})
        if '자재ㆍ공법 선정심의 결과표' not in text_of(soup):raise FeedError('partner_schema','선정심의 결과 확인 실패')
    else:
        pattern='tech_app_view.asp' if kind=='기술 반영' else 'r_view.asp' if kind=='심의위원 선정' else 'notice_view.asp'
        for a in soup.select('[onclick]'):
            if pattern not in a.get('onclick',''):continue
            tr=a.find_parent('tr')
            if tr is None:continue
            link=get_link(a,BASE+path);match=re.search(r'[?&]idx=(\d+)',link)
            if not match:raise FeedError('partner_schema','게시물 번호 확인 실패')
            tds=tr.find_all('td',recursive=False)
            rows.append({'key':match[1],'title':text_of(a),'list_date':date_key(text_of(tds[2])) if kind!='기술 반영' and len(tds)>2 else '', 'list_date_label':'작성일' if kind!='기술 반영' else '등록일 미제공','list_text':text_of(tr),'detail':link,'post':None})
        expected='특정공법·자재 반영 현황' if kind=='기술 반영' else '심의위원 선정결과' if kind=='심의위원 선정' else '공지사항'
        if expected not in text_of(soup):raise FeedError('partner_schema','게시판 제목 확인 실패')
    if not rows and not re.search(r'(등록된|검색된|조회된|해당|검색 결과).*?(없습니다|없음)|\$\$0',text_of(soup)+' '+raw):
        raise FeedError('partner_schema','빈 목록인지 게시판 구조 변경인지 확정할 수 없습니다')
    unique={r['key']:r for r in rows}
    pages=[int(n) for n in re.findall(r'page=(\d+)',raw)]
    match=re.search(r'var page_count\s*=\s*"(\d+)"',raw)
    if match:pages.append(int(match[1]))
    if '$$' in raw:
        try:pages.append(int(raw.rsplit('$$',1)[1].strip()))
        except ValueError:raise FeedError('partner_schema','결과 페이지 수 확인 실패')
    return list(unique.values()),max(pages or [1])

def detail_fields(raw):
    soup=soup_of(raw);box=soup.select_one('.content_box') or soup
    fields={}
    for th in box.find_all('th'):
        td=th.find_next_sibling('td')
        if td:fields[text_of(th)]=text_of(td)
    return box,fields

def attachments(client,box,base,cache):
    files=[];texts=[];issues=[]
    for a in box.find_all('a'):
        link=get_link(a,base)
        if '/common/download.asp?' not in link:continue
        name=text_of(a)
        if link in {f['url'] for f in files}:continue
        if len(files)>=12:issues.append('첨부파일 개수 제한');break
        try:
            data,headers=client.request(link,binary=True);client.attachment_count+=1
            if name.lower() in ('다운로드','첨부파일 다운로드'):
                disposition=headers.get('Content-Disposition','');m=re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)",disposition,re.I)
                name=unquote(m[1]) if m else name
            fingerprint=hashlib.sha256(data).hexdigest()
            cached=cache.get(link)
            if cached and cached.get('sha256')==fingerprint:text=cached.get('text','')
            else:text=extract(data,name);cache[link]={'sha256':fingerprint,'text':text}
            files.append({'name':name,'url':link,'sha256':fingerprint,'text_checked':True});texts.append(text)
        except Exception as ex:
            files.append({'name':name,'url':link,'text_checked':False});issues.append(type(ex).__name__+': 첨부 본문 검토 미완료')
    return files,'\n'.join(texts),issues

def fetch_board(client,board,until,cache):
    category,path,query,stage=board;items=[];scanned=0;excluded=0;issues=[];seen=set();last_signature=None
    for page in range(1,101):
        raw=client.request(BASE+path,dict(query,page=str(page)))
        rows,pages=parse_rows(raw,stage,path)
        if pages>100:raise FeedError('partner_limit','게시판 페이지 상한 초과')
        signature=digest([r['key'] for r in rows])
        if page>1 and rows and signature==last_signature:raise FeedError('repeated_page','게시판이 같은 페이지를 반복 반환합니다')
        last_signature=signature
        for row in rows:
            if row['key'] in seen:continue
            seen.add(row['key']);scanned+=1
            if row['list_date'] and row['list_date']<START_DATE:excluded+=1;continue
            if row['list_date'] and row['list_date']>until:continue
            detail=client.request(row['detail'],row['post'])
            box,fields=detail_fields(detail)
            official_date=next((date_key(fields[k]) for k in ('작성일','등록일','공모일') if date_key(fields.get(k))),row['list_date'])
            date_label=next((k for k in ('작성일','등록일','공모일') if date_key(fields.get(k))),row['list_date_label'])
            if official_date and official_date<START_DATE:excluded+=1;continue
            files,attachment_text,file_issues=attachments(client,box,row['detail'],cache)
            # Do not fingerprint view counts, navigation, timestamps or script content.
            body=' '.join(text_of(x) for x in box.select('td')) or text_of(box)
            context=row['title']+' '+row['list_text']+' '+body+' '+attachment_text
            if file_issues:issues.extend(row['key']+': '+x for x in file_issues)
            if not relevant(context):continue
            if not official_date:
                issues.append(row['key']+': 지역 일치, 원문 날짜 미제공으로 기간 확정 불가');continue
            if official_date>until:continue
            ident=digest([SERVICE,category,row['key']])
            source_detail_verified=row['post'] is None
            title=row['title']
            if not relevant(title):title='성남금토 관련 · '+title
            item={'id':ident,'fingerprint':digest([row['title'],fields,{k:v for k,v in row.items() if k in ('list_date','list_text','vendor')},files]),'title':title,'service':SERVICE,'category':category,'stage':stage,'base_stage':stage,'date':official_date,'date_label':date_label,'publication_date':official_date,'agency':'한국토지주택공사','notice_id':row['key'],'sequence':'','amounts':[],'amount':'','url':row['detail'] if source_detail_verified else BASE+('/deliberate/deliberate.asp' if stage=='공모' else '/deliberate/deliberate_r.asp'),'source_detail_verified':source_detail_verified,'areas':areas_for(context),'references':{},'vendor':row.get('vendor',''),'attachments':files,'relevance_basis':'목록·원문·첨부 본문에서 성남금토 연관성 확인','source_fields':fields,'evidence':'공식 공개 게시판 번호 '+row['key']}
            # Fields such as views are not material; retain only semantic labels.
            stable={k:v for k,v in fields.items() if k not in ('조회수','조회','이전글','다음글','이전','다음')}
            item['fingerprint']=digest([row['title'],stable,text_of(box.select_one('.view_cont')),row['list_date'],row.get('vendor'),files])
            items.append(item)
        dated=[r['list_date'] for r in rows if r['list_date']]
        if page>=pages or (dated and max(dated)<START_DATE) or not rows:break
    else:raise FeedError('partner_limit','게시판 조회 상한 초과')
    status={'dataset':'partner','service':SERVICE,'category':category,'status':'성공' if not issues else '조회 불완전','code':'ok' if not issues else 'attachment_or_date_unverified','detail':f'공개 목록 {scanned}건 확인 / 시작일 이전 {excluded}건 제외 / 기간·지역 일치 {len(items)}건'+(' / '+('; '.join(issues))[:200] if issues else ''),'matched_count':len(items),'scanned_count':scanned,'excluded_before_start':excluded,'checked_at':datetime.now(KST).isoformat(timespec='seconds')}
    return items,status

def collect(session,until,cache=None):
    cache=cache if cache is not None else {};items=[];statuses=[]
    try:client=PublicClient(session)
    except Exception:
        return [],[{'dataset':'partner','service':SERVICE,'category':b[0],'status':'조회 실패','code':'robots_or_network','detail':'공개 조회 정책 또는 연결 확인 실패'} for b in BOARDS],cache
    for board in BOARDS:
        try:
            found,status=fetch_board(client,board,until,cache);items.extend(found)
        except Exception as ex:
            status={'dataset':'partner','service':SERVICE,'category':board[0],'status':'조회 실패','code':ex.code if isinstance(ex,FeedError) else 'network_or_schema_error','detail':str(ex)[:180] if isinstance(ex,FeedError) else '공개 게시판 연결 또는 구조 확인 실패'}
        statuses.append(status)
        print({'partner_board':board[0],'status':status['status'],'code':status['code']},flush=True)
    return items,statuses,cache
