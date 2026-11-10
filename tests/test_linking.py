from app.linking import merge_latest,explicit_related

def row(ident,source,agency,number='N1',sequence='001',stage='입찰공고'):
    return {'id':ident,'service':source,'agency':agency,'notice_id':number,'sequence':sequence,'base_stage':stage}

def test_same_lh_notice_merges_but_preserves_both_sources():
    a=row('a','나라장터','한국토지주택공사 경기남부지역본부')
    b=row('b','LH 전자조달','경기남부')
    result=merge_latest([a,b])
    assert len(result)==1 and len(result[0]['sources'])==2

def test_same_number_other_agency_or_sequence_or_stage_stays_separate():
    a=row('a','나라장터','한국토지주택공사')
    assert len(merge_latest([a,row('b','나라장터','성남시')]))==2
    assert len(merge_latest([a,row('b','LH 전자조달','LH',sequence='002')]))==2
    assert len(merge_latest([a,row('b','LH 전자조달','LH',stage='개찰결과')]))==2

def test_missing_sequence_is_not_guessed():
    assert len(merge_latest([row('a','나라장터','한국토지주택공사',sequence=''),row('b','LH 전자조달','LH',sequence='')]))==2

def test_explicit_prespec_reference_links_stages():
    spec=row('spec','나라장터','한국토지주택공사',number='SPEC1',stage='사전규격')
    bid=row('bid','나라장터','한국토지주택공사');bid['references']={'bfSpecRgstNo':'SPEC1'}
    assert explicit_related(bid,[spec,bid])==[spec]
