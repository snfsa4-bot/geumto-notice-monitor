from app.collector import relevant, parse_response, normalize

def test_filter_strong():
    assert relevant('성남금토 A-4BL 실내조명')
    assert relevant('성남 금토2지구 환경평가')
    assert not relevant('부산 A-4BL 신혼희망타운')
    assert not relevant('금토일 도시행사')

def test_xml_records():
    raw='<response><header><resultCode>00</resultCode></header><body><items><item><bidNtceNm>성남금토 도로</bidNtceNm><bidNtceNo>26001</bidNtceNo></item></items></body></response>'
    assert parse_response(raw)[0]['bidNtceNo']=='26001'

def test_json_records():
    raw='{"response":{"header":{"resultCode":"00"},"body":{"items":[{"bidNtceNm":"성남금토 A-4BL"}]}}}'
    assert len(parse_response(raw))==1

def test_normalization_rejects_nonlocal_title():
    assert normalize({'bidNtceNm':'부산 A-4BL'},'나라장터','물품','입찰') is None

def test_normalization_normal():
    a=normalize({'bidNtceNm':'성남금토 A-4BL 조명','bidNtceNo':'123','bidNtceDt':'20261110'},'나라장터','물품','입찰')
    assert a['notice_id']=='123'
    assert a['service']=='나라장터'
