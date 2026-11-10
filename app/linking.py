"""Conservative cross-source matching; preserve every source and stage record."""
from app.collector import compact

def agency_key(record):
    agency=compact(record.get('agency',''))
    if record.get('service')=='LH 전자조달' or '한국토지주택공사' in agency:
        return '한국토지주택공사'
    return agency

def duplicate_key(record):
    # A missing notice number, agency or sequence is insufficient for cross-source merging.
    agency=agency_key(record)
    notice=compact(record.get('notice_id',''))
    sequence=record.get('sequence','')
    if not notice or not agency or not sequence:
        return ('unmatched',record['id'])
    return (record.get('base_stage',record.get('stage')),notice,str(sequence),agency)

def merge_latest(records):
    groups={}
    for r in records:
        key=duplicate_key(r)
        if key not in groups:
            groups[key]=dict(r,sources=[{'id':r['id'],'service':r.get('service','출처 미확인'),'url':r.get('url','')}])
        else:
            groups[key]['sources'].append({'id':r['id'],'service':r.get('service','출처 미확인'),'url':r.get('url','')})
    return list(groups.values())

def explicit_related(record,records):
    refs=set(str(v) for v in record.get('references',{}).values() if v)
    notice=str(record.get('notice_id',''))
    result=[]
    for other in records:
        if other['id']==record['id']:continue
        other_refs=set(str(v) for v in other.get('references',{}).values() if v)
        other_notice=str(other.get('notice_id',''))
        if (notice and other_notice and notice==other_notice and agency_key(record) and agency_key(record)==agency_key(other)) or (other_notice and other_notice in refs) or (notice and notice in other_refs):
            result.append(other)
    return result
