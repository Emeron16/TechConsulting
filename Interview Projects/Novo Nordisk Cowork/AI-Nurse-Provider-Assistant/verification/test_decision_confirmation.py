"""Dashboard confirmation regression checks; no live model or demo database writes."""
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from core.schemas import ExtractedRequest, PolicyAnalysis, RiskRouting


def case(identifier):
    return dict(id=identifier, created_at='2026-09-26', pathway='standard_review',
        matched_policy_id=None, status='queued_for_review',
        extracted_json=ExtractedRequest(patient_id='SYNTHETIC', date_of_birth='1990-01-01',
            requesting_provider='Demo Provider', clinical_notes='Synthetic test', urgency='routine',
            confidence_score=.9).model_dump_json(),
        policy_analysis_json=PolicyAnalysis(patient_summary='Synthetic patient',
            request_summary='Synthetic request', recommendation='needs_review', confidence=.8,
            estimated_review_minutes=10, rationale='Review needed').model_dump_json(),
        routing_json=RiskRouting(pathway='standard_review', sla_hours=24,
            requires_human_review=True, reason='Review needed').model_dump_json())


class ConfirmationTest(unittest.TestCase):
    def exercise(self, count, decision='approved', failure=False, reviewer=True):
        rows = [case(f'TEST-{i}') for i in range(count)]
        def update(identifier, **fields):
            next(row for row in rows if row['id'] == identifier).update(fields)
        with patch('core.config.require_client_or_stop'), \
             patch('core.store.list_requests', side_effect=lambda **kw: [r for r in rows if r['status']=='queued_for_review']), \
             patch('core.store.update_request', side_effect=update) as saved, \
             patch('core.store.log_audit') as audit, \
             patch('core.letters.generate_decision_letter', side_effect=RuntimeError('Synthetic failure') if failure else None, return_value='Draft letter'):
            app = AppTest.from_file('pages/2_Nurse_Dashboard.py').run()
            self.assertFalse(app.exception)
            if reviewer:
                app.text_input[0].set_value('Demo Nurse')
            label = '✅ Approve' if decision=='approved' else '❌ Deny'
            next(b for b in app.button if b.label==label).click().run()
            confirmations = lambda: [x.value for x in app.success if 'Decision recorded:' in x.value]
            if failure or not reviewer:
                self.assertEqual(confirmations(), [])
                saved.assert_not_called()
                audit.assert_not_called()
                return
            self.assertFalse(app.exception)
            self.assertEqual(confirmations(), [f'Decision recorded: TEST-0 — {decision}.'])
            self.assertEqual(rows[0]['decision_letter'], 'Draft letter')
            audit.assert_called_once()
            app.run()
            self.assertEqual(len(confirmations()), 1)
            next(b for b in app.button if b.label=='Dismiss confirmation').click().run()
            self.assertEqual(confirmations(), [])

    def test_last_approval(self): self.exercise(1)
    def test_remaining_queue(self): self.exercise(2)
    def test_denial(self): self.exercise(1, decision='denied')
    def test_missing_name(self): self.exercise(1, reviewer=False)
    def test_letter_failure(self): self.exercise(1, failure=True)

if __name__ == '__main__': unittest.main()
