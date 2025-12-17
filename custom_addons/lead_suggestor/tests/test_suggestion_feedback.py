from odoo.tests import tagged
from .test_property_common import PropertyInventoryTestCase

@tagged('post_install', '-at_install')
class TestSuggestionFeedback(PropertyInventoryTestCase):
    """Test feedback logging functionality"""

    def test_01_action_log_feedback_returns_wizard(self):
        """Should return wizard action to log feedback."""
        suggestion = self.create_suggestion()
        action = suggestion.action_log_feedback()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'suggestion.feedback.wizard')
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['target'], 'new')
    
    def test_02_action_log_feedback_passes_context(self):
        """Feedback wizard should receive suggestion context"""
        suggestion = self.create_suggestion(
            status = 'contacted',
            rm_feedback = "Initial contact made"
        )

        action = suggestion.action_log_feedback()
        context = action.get('context', {})

        self.assertEqual(context['default_suggestion_id'], suggestion.id)
        self.assertEqual(context['default_status'], 'contacted')
        self.assertEqual(context['default_rm_feedback'], "Initial contact made")

    def test_03_rm_feedback_field_storage(self):
        """Should store RM feedback text."""
        suggestion = self.create_suggestion()
        feedback = "Contacted lead, interested in property."

        suggestion.rm_feedback = feedback

        self.assertEqual(suggestion.rm_feedback, feedback)

    def test_04_status_transitions(self):
        """Should allow status transitions."""
        suggestion = self.create_suggestion(status='new')

        suggestion.status = 'contacted'
        self.assertEqual(suggestion.status, 'contacted')

        suggestion.status = 'converted'
        self.assertEqual(suggestion.status, 'converted')
        
        suggestion.status = 'interested'
        self.assertEqual(suggestion.status, 'interested')