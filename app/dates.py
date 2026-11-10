"""Date boundaries for the requested monitoring period."""
import re
from datetime import date,datetime,timedelta
START_DATE='2026-10-01'
def date_key(value):
    s=str(value or '').strip()
    match=re.match(r'(?P<year>20\d{2})[-./]?(?P<month>\d{2})[-./]?(?P<day>\d{2})',s)
    if not match:
        short=re.match(r'(\d{2})\.(\d{2})\.(\d{2})',s)
        if not short:return ''
        parts=(2000+int(short[1]),int(short[2]),int(short[3]))
    else:parts=tuple(int(match[n]) for n in ('year','month','day'))
    try:return date(*parts).isoformat()
    except ValueError:return ''
def in_scope(value,end=None):
    key=date_key(value)
    return bool(key and key>=START_DATE and (end is None or key<=date_key(end)))
def windows(start,end,days=7):
    current=start
    while current<end:
        stop=min(current+timedelta(days=days),end)
        yield current,stop
        current=stop
