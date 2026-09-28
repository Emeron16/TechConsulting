from pathlib import Path
import json,time
from core import store
from core.pipeline import run_pipeline
from core.cowork_bridge import session_status
store.init_db()
for _ in range(90):
    if session_status()['active']:break
    time.sleep(1)
else:raise RuntimeError('Cowork did not start')
results=[]
for f in sorted(Path('data/sample_requests').glob('*.txt')):
    t=time.time();r=run_pipeline(f.read_text(),source='sample')
    item={'sample':f.name,'request_id':r.request_id,'status':r.status,'pathway':r.routing.pathway if r.routing else None,'decision':r.decision,'seconds':round(time.time()-t,1)}
    results.append(item);Path('verification/live-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(item),flush=True)
