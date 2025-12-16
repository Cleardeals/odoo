# -*- coding: utf-8 -*-
from odoo.tests import tagged
from datetime import timedelta
from odoo import fields
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadCron(PortalLeadTestCase):
    """
    Test cron job operations for re-processing stuck leads.
    """

    def test_01_cron_reprocesses_old_unassigned_leads(self):
        """Cron should reprocess leads older than 1 hour."""
        # 1. Create old unassigned lead
        # [FIX] Use dynamic ID (self.mb_id) so the logic actually finds the property
        lead = self.create_portal_lead(
            portal_name='MagicBricks',
            portal_property_id=self.mb_id, 
            state='new'
        )
        
        # 2. Make it old (2 hours ago) via SQL to bypass ORM readonly
        old_date = fields.Datetime.now() - timedelta(hours=2)
        self.env.cr.execute(
            "UPDATE leads_new SET create_date = %s WHERE id = %s",
            (old_date, lead.id)
        )
        lead.invalidate_recordset()
        
        # 3. Run cron
        self.env['leads.new']._cron_reprocess_unassigned_leads()
        
        # 4. Verify it was processed
        lead.invalidate_recordset()
        self.assertEqual(lead.state, 'assigned', "Old 'new' lead should be auto-processed by cron")
        self.assertEqual(lead.property_id, self.test_property, "Lead should be linked to property")

    def test_02_cron_skips_recent_leads(self):
        """Cron should not process leads less than 1 hour old."""
        # 1. Create fresh lead
        lead = self.create_portal_lead(
            portal_property_id=self.mb_id,
            state='new'
        )
        
        # 2. Run cron
        self.env['leads.new']._cron_reprocess_unassigned_leads()
        
        # 3. Should still be new (too recent to touch)
        lead.invalidate_recordset()
        self.assertEqual(lead.state, 'new', "Recent lead should be ignored by cron")

    def test_03_cron_skips_already_assigned(self):
        """Cron should skip already assigned leads."""
        # 1. Create Assigned Lead
        lead = self.create_portal_lead(
            state='assigned',
            user_id=self.rm_user.id
        )
        
        # 2. Make it old
        old_date = fields.Datetime.now() - timedelta(hours=2)
        self.env.cr.execute(
            "UPDATE leads_new SET create_date = %s WHERE id = %s",
            (old_date, lead.id)
        )
        lead.invalidate_recordset()
        
        # 3. Run cron
        self.env['leads.new']._cron_reprocess_unassigned_leads()
        
        # 4. Should remain assigned to original RM
        lead.invalidate_recordset()
        self.assertEqual(lead.user_id, self.rm_user, "Assigned lead should not be touched")