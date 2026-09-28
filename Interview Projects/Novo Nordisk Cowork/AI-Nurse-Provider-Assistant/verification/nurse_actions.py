import json,time
from pathlib import Path
from streamlit.testing.v1 import AppTest
from core import store
results=[]
for cid,button,decision in [('PA-20260925-0001','✅ Approve','approved'),('PA-20260925-0002','✉️ Request more info','information_requested'),('PA-20260925-0003','❌ Deny','denied')]:
 at=AppTest.from_file('pages/2_Nurse_Dashboard.py',default_timeout=240).run()
 assert not at.exception
 at.text_input[0].set_value('Demo Nurse')
 at.selectbox[0].select(cid).run()
 at.text_area[0].set_value('Synthetic demonstration: additional conservative treatment documentation is required.' if decision=='information_requested' else 'Synthetic demonstration: reviewer has assessed the supplied fictional policy and records this test decision.')
 next(b for b in at.button if b.label==button).click().run(timeout=240)
 assert not at.exception,[e.message for e in at.exception]
 row=store.get_request(cid)
 assert row['status']==('information_requested' if decision=='information_requested' else 'decided'),row
 if decision!='information_requested': assert row['decision']==decision and row['decision_letter']
 else:assert row['missing_info_letter']
 results.append({'request_id':cid,'action':decision,'status':row['status'],'letter_saved':True})
 Path('verification/nurse-results.json').write_text(json.dumps(results,indent=2));print(results[-1],flush=True)
