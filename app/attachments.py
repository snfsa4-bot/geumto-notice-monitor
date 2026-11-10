"""Read bounded public documents as text; never execute their contents."""
import io,zipfile,zlib,struct
import xml.etree.ElementTree as ET
from pypdf import PdfReader
import olefile
LIMIT=20*1024*1024
class AttachmentError(ValueError):pass

def extract(data,name='',depth=0):
    if len(data)>LIMIT or depth>2:raise AttachmentError('첨부파일 크기·중첩 제한')
    suffix=name.lower().rsplit('.',1)[-1]
    if data.startswith(b'%PDF'):
        doc=PdfReader(io.BytesIO(data))
        if len(doc.pages)>200:raise AttachmentError('PDF 페이지 제한')
        text='\n'.join(p.extract_text() or '' for p in doc.pages)
        if not text.strip():raise AttachmentError('문자 없는 PDF: OCR 검토 필요')
        return text
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files=archive.infolist()
            if len(files)>300 or sum(f.file_size for f in files)>LIMIT:raise AttachmentError('압축 해제 크기 제한')
            if suffix in ('hwpx','docx','xlsx') or any(f.filename.startswith(('Contents/section','word/document','xl/sharedStrings')) for f in files):
                texts=[]
                for f in files:
                    if f.filename.endswith('.xml') and f.filename.startswith(('Contents/section','word/document','xl/sharedStrings','xl/worksheets')):
                        root=ET.fromstring(archive.read(f));texts.append(' '.join(root.itertext()))
                if not texts:raise AttachmentError('문서 XML 미확인')
                return '\n'.join(texts)
            texts=[];errors=[]
            for f in files:
                if f.is_dir():continue
                if f.filename.lower().endswith(('.pdf','.hwp','.hwpx','.docx','.xlsx','.txt','.zip')):
                    try:texts.append(extract(archive.read(f),f.filename,depth+1))
                    except Exception as ex:errors.append(type(ex).__name__)
            if errors or not texts:raise AttachmentError('압축파일 일부 문서 추출 불완전')
            return '\n'.join(texts)
    if olefile.isOleFile(io.BytesIO(data)):
        with olefile.OleFileIO(io.BytesIO(data)) as doc:
            if not doc.exists('FileHeader'):raise AttachmentError('지원하지 않는 OLE 문서')
            flags=struct.unpack_from('<I',doc.openstream('FileHeader').read(),36)[0]
            if flags&2:raise AttachmentError('암호화된 HWP')
            chunks=[];remaining=LIMIT
            for path in doc.listdir():
                if len(path)==2 and path[0]=='BodyText' and path[1].startswith('Section'):
                    raw=doc.openstream(path).read()
                    if flags&1:
                        decoder=zlib.decompressobj(-15);raw=decoder.decompress(raw,LIMIT+1)
                        if len(raw)>LIMIT:raise AttachmentError('HWP 압축 해제 제한')
                    remaining-=len(raw)
                    if remaining<0:raise AttachmentError('HWP 전체 본문 크기 제한')
                    offset=0
                    while offset+4<=len(raw):
                        header=struct.unpack_from('<I',raw,offset)[0];offset+=4
                        tag=header&1023;size=(header>>20)&4095
                        if size==4095:
                            size=struct.unpack_from('<I',raw,offset)[0];offset+=4
                        if size>LIMIT or offset+size>len(raw):raise AttachmentError('HWP 레코드 오류')
                        if tag==67:chunks.append(raw[offset:offset+size].decode('utf-16le',errors='replace'))
                        offset+=size
            text='\n'.join(chunks)
            if not text.strip():raise AttachmentError('HWP 본문 확인 실패')
            return text
    if suffix in ('txt','csv'):
        for encoding in ('utf-8','cp949'):
            try:return data.decode(encoding)
            except UnicodeDecodeError:pass
    raise AttachmentError('지원하지 않는 첨부 형식')
