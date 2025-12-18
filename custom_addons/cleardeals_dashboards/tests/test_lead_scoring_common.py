from odoo.tests.common import TransactionCase
from datetime import datetime
import time

class LeadScoringTestCase(TransactionCase):
    """
    Base Test Case for lead scoring tests.
    Provides reusable fixtures, helper methods and mock data.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Initialize a counter to ensure unique phone numbers during rapid creation
        cls._phone_counter = 0
        cls.timestamp = str(int(time.time()))

        # Template names used in the system
        cls.TEMPLATE_TRIGGERS = [
            'ringing',
            'detail_shared_of_property_message',
            'site_visit_schedule_reminder',
            'site_visit_schedule_after_visit'
        ]

        cls.TEMPLATE_RESPONSES = [
            'going_for_visit_today',
            'need_help_for_site_visit_today',
            'visit_done_response_after_site_visit',
            'liked_property_after_site_visit',
            'call_the_expert_after_site_vist',
            'reschedule_visit_response',
            'ringing_abhi_call_kare',
            'ringing_slot_book_kare',
            'schedule_visit_now_response',
            'talk_to_a_property_expert_response'
        ]

    def create_lead(self, **kwargs):
        """Helper to create a lead with sensible defaults and GUARANTEED unique phone."""
        # Increment counter to ensure uniqueness even if code runs in same ms
        self.__class__._phone_counter += 1
        unique_suffix = f"{int(time.time())}{self.__class__._phone_counter}"[-5:]
        
        # Ensure phone is always unique: 99 + last 5 digits of time + counter
        unique_phone = f'99{unique_suffix.zfill(8)}'

        values = {
            'lead_name': 'Test Lead',
            'lead_phone': kwargs.get('lead_phone', unique_phone), # Allow override
            'property_tag': f'PROP-{unique_suffix}',
            'assigned_rm': 'Test RM',
            'predicted_score': 0.85,
            'current_status': 'lead',
            'workflow_stage': 'ringing',
        }
        # Update with any specific overrides passed to the method
        # (Exclude lead_phone if it was handled above to prevent overwriting if passed in kwargs)
        if 'lead_phone' in kwargs:
            del kwargs['lead_phone']
            
        values.update(kwargs)
        return self.env['lead.scoring.lead'].create(values)
    
    def create_event(self, lead=None, **kwargs):
        """Helper to create an event with defaults."""
        if lead is None:
            lead = self.create_lead()
        
        self.__class__._phone_counter += 1
        unique_id = f"{int(time.time())}_{self.__class__._phone_counter}"

        values = {
            'lead_id': lead.id,
            'event_id': f'evt_{unique_id}',
            'correlation_id': f'corr_{unique_id}',
            'event_timestamp': datetime.now(),
            'event_type': 'message_sent',
            'message_direction': 'outbound',
            'message_content': 'Test message',
            'template_name': 'ringing',
        }
        values.update(kwargs)
        return self.env['lead.scoring.event'].create(values)
    
    def create_outbound_sent_event(self, lead, template_name, correlation_id=None):
        """Create a message_sent outbound event."""
        if correlation_id is None:
            self.__class__._phone_counter += 1
            correlation_id = f'corr_{int(time.time())}_{self.__class__._phone_counter}'
        
        return self.create_event(
            lead=lead,
            event_type='message_sent',
            message_direction='outbound',
            template_name=template_name,
            correlation_id=correlation_id
        )
    
    def create_status_event(self, lead, status_type, correlation_id):
        """Create a status event (delivered/read/failed)."""
        return self.create_event(
            lead=lead,
            event_type=status_type,
            message_direction='outbound',
            correlation_id=correlation_id,
            template_name=False
        )
    
    def create_inbound_event(self, lead, message_content='Customer reply'):
        """Create an inbound message event."""
        return self.create_event(
            lead=lead,
            event_type='message_received',
            message_direction='inbound',
            message_content=message_content,
            template_name=False
        )