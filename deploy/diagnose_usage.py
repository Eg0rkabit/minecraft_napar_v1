"""Read-only accounting summary. No provider requests or credentials printed."""
import json
from pathlib import Path
import sqlite3

base=Path('/opt/napar-next/brain')
c=sqlite3.connect('file:'+str(base/'data/napar.db')+'?mode=ro',uri=True)
result={
 'usage':c.execute('select * from usage').fetchall(),
 'completed_cycles':c.execute('select json_extract(payload,?),count(*) from audit where kind=? group by 1',('$.trigger','reasoning')).fetchall(),
 'provider_errors':c.execute('select json_extract(payload,?),count(*) from audit where kind=? group by 1',('$.status','provider_error')).fetchall(),
 'goals':c.execute('select status,substr(description,1,100),substr(summary,1,100) from goals order by updated desc limit 5').fetchall(),
 'autonomy':c.execute('select autonomy from preferences').fetchall(),
}
print(json.dumps(result,ensure_ascii=False,indent=2))

