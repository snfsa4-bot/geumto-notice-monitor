from app.verify import compare

def test_independent_comparison_rejects_opening_date_as_publication_date():
    notice={'title':'성남금토2 측량','notice_id':'2603962','base_stage':'입찰공고','date':'2026/11/18 11:00','amounts':[{'field':'fdmtlAmt','value':'43208000'}]}
    raw={'bidnmKor':'성남금토2 측량','bidNum':'2603962','tndrbidRegDt':'20261109','openDtm':'2026/11/18 11:00','fdmtlAmt':'43208000'}
    result=compare(notice,raw)
    assert result['title'] and result['number'] and result['amounts'] and not result['date']
