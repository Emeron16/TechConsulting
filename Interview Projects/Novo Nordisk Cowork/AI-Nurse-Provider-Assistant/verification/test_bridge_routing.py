import importlib,tempfile,unittest,json,time
from pathlib import Path
from core import cowork_bridge as b
from core.routing import route
from core.schemas import ExtractedRequest,PolicyAnalysis
from core.policy_rag import get_policy
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.old=b.QUEUE;b.QUEUE=Path(self.t.name)
 def tearDown(self):b.QUEUE=self.old;self.t.cleanup()
 def test_offline_fails_without_queueing(self):
  with self.assertRaises(RuntimeError):b.CoworkClient()._request([])
  self.assertEqual(list(b.QUEUE.glob('*.job.json')),[])
 def test_late_result_cannot_complete_failed_job(self):
  jid='a'*24;b.save(b.QUEUE/(jid+'.job.json'),{'status':'failed'})
  with self.assertRaises(ValueError):b.complete(jid,'nonexistent')
 def test_bad_structured_response_rejected(self):
  with self.assertRaises(ValueError):b.validate_shape({'urgency':'invented'},ExtractedRequest.model_json_schema())
 def test_stop_signal(self):
  (b.QUEUE/'STOP').touch();b.next_job(1);self.assertFalse(b.session_status()['active'])
 def request(self,urgency='routine'):
  return ExtractedRequest(patient_id='SYN',date_of_birth='2000-01-01',diagnosis_codes=['M54.5'],procedure_codes=['97161'],requesting_provider='Synthetic',clinical_notes='Synthetic notes',urgency=urgency,confidence_score=.99)
 def analysis(self,confidence=.95,**kw):
  return PolicyAnalysis(patient_summary='Synthetic',request_summary='Synthetic',recommendation='likely_approve',confidence=confidence,estimated_review_minutes=5,rationale='Test',**kw)
 def test_auto_approval_threshold(self):
  pol=get_policy('PT-EVAL-001');self.assertEqual(route(self.request(),self.analysis(),pol).pathway,'auto_approve');self.assertEqual(route(self.request(),self.analysis(.949),pol).pathway,'fast_track')
 def test_risk_blocks_autoapproval(self):self.assertEqual(route(self.request(),self.analysis(risk_flags=['test risk']),get_policy('PT-EVAL-001')).pathway,'standard_review')
 def test_unmet_prevents_autoapproval(self):self.assertNotEqual(route(self.request(),self.analysis(unmet_criteria=['test unmet']),get_policy('PT-EVAL-001')).pathway,'auto_approve')
 def test_urgent_overrides_autoapproval(self):self.assertEqual(route(self.request('urgent'),self.analysis(),get_policy('PT-EVAL-001')).pathway,'urgent')
if __name__=='__main__':unittest.main()
