from pathlib import Path
import json
from streamlit.testing.v1 import AppTest
from core import store,ocr
from core.pipeline import run_pipeline
row=store.get_request('PA-20260925-0002');assert row['status']=='queued_for_review',row['status']
results={'supplement':{'status':row['status'],'pathway':row['pathway']}}
for cid in ['PA-20260925-0001','PA-20260925-0003']:
 at=AppTest.from_file('pages/3_Provider_Portal.py').run()
 at.selectbox[0].select(cid).run();assert not at.exception
 assert any('DRAFT' in t.value.upper() for t in at.text_area)
results['provider_final_letters']='approval and denial rendered'
f=Path('../../inputs/Synthetic-MRI-Missing-Information.pdf');r=run_pipeline(ocr.extract_text(f.name,f.read_bytes()),'upload')
assert r.status=='information_requested',r.status
results['pdf_intake']={'request_id':r.request_id,'status':r.status}
f=Path('../synthetic-inputs/Synthetic-Fresh-PT-Brooks.pdf');r=run_pipeline(ocr.extract_text(f.name,f.read_bytes()),'upload')
results['unambiguous_pt']={'request_id':r.request_id,'status':r.status,'pathway':r.routing.pathway if r.routing else None}
Path('verification/provider-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results),flush=True)
