# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
import time

class PortalLeadTestCase(TransactionCase):
    """
    Base Fixture for Portal Leads.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Unique suffix for this test run
        cls.suffix = str(int(time.time()))
        user_model = cls.env['res.users'].sudo()
        cls.rm_user = cls.env.ref('base.user_admin')
        cls.naresh_user = user_model.search([('name', '=', 'Naresh Rojiya')], limit=1) or cls.rm_user
        cls.pratham_user = user_model.search([('name', '=', 'Pratham Bhandari')], limit=1) or cls.naresh_user
        cls.mayuri_user = user_model.search([('name', '=', 'Mayuri Malivad')], limit=1) or cls.naresh_user

        # Create Property with UNIQUE IDs
        cls.mb_id = f'MB_{cls.suffix}'
        cls.hsg_id = f'HSG_{cls.suffix}'
        cls.acres_id = f'99_{cls.suffix}'
        cls.olx_id = f'OLX_{cls.suffix}'

        cls.test_property = cls.env['property.base'].create({
            'property_tag': f'TEST-PROP-{cls.suffix}',
            'name': f'Test Property {cls.suffix}',
            'prop_id': f'TP{cls.suffix}',  # drives computed property_link
            'bedroom_count': 3,             # drives computed bhk ('3 BHK')
            'location': 'Test Location',
            'city': 'Test City',
            'rm_user_id': cls.rm_user.id,
            'is_active': True,
            'portal_listing_ids': [
                (0, 0, {
                    'portal_name': 'MagicBricks',
                    'portal_listing_id': cls.mb_id,
                    'listing_label': f'MagicBricks | {cls.mb_id}',
                    'active': True,
                }),
                (0, 0, {
                    'portal_name': 'Housing.com',
                    'portal_listing_id': cls.hsg_id,
                    'listing_label': f'Housing.com | {cls.hsg_id}',
                    'active': True,
                }),
                (0, 0, {
                    'portal_name': '99acres',
                    'portal_listing_id': cls.acres_id,
                    'listing_label': f'99acres | {cls.acres_id}',
                    'active': True,
                }),
                (0, 0, {
                    'portal_name': 'OLX',
                    'portal_listing_id': cls.olx_id,
                    'listing_label': f'OLX | {cls.olx_id}',
                    'active': True,
                }),
            ],
        })

        # Keep source defaults aligned with processing fallback expectations.
        cls.source_magicbricks = cls._ensure_source(
            name='MagicBricks',
            source_type='portal',
            portal_code='MagicBricks',
            default_rm_user=cls.mayuri_user,
        )
        cls.source_housing = cls._ensure_source(
            name='Housing.com',
            source_type='portal',
            portal_code='Housing.com',
            default_rm_user=cls.naresh_user,
        )
        cls.source_99acres = cls._ensure_source(
            name='99acres',
            source_type='portal',
            portal_code='99acres',
            default_rm_user=cls.pratham_user,
        )
        cls.source_olx = cls._ensure_source(
            name='OLX',
            source_type='portal',
            portal_code='OLX',
            default_rm_user=cls.naresh_user,
        )
        cls.source_unknown = cls._ensure_source(
            name='UnknownPortal',
            source_type='manual',
            default_rm_user=cls.naresh_user,
        )

    @classmethod
    def _ensure_source(
        cls,
        name,
        source_type='portal',
        portal_code=False,
        default_rm_user=False,
    ):
        source_model = cls.env['lead.source'].sudo()
        category_model = cls.env['lead.source.category'].sudo()

        source = source_model.search([('name', '=', name)], limit=1)
        if not source:
            if source_type == 'portal':
                category = cls.env.ref(
                    'leads.lead_source_category_portal',
                    raise_if_not_found=False,
                ) or category_model.search([('source_type', '=', 'portal')], limit=1)
                if not category:
                    category = category_model.create({
                        'name': 'Portals',
                        'code': 'portals',
                        'source_type': 'portal',
                    })
                source = source_model.create({
                    'name': name,
                    'category_id': category.id,
                    'portal_code': portal_code or name,
                })
            else:
                category = category_model.search(
                    [('source_type', '=', 'manual')],
                    order='sequence, id',
                    limit=1,
                )
                if not category:
                    category = category_model.create({
                        'name': 'Manual',
                        'code': 'manual',
                        'source_type': 'manual',
                    })
                source = source_model.create({
                    'name': name,
                    'category_id': category.id,
                })

        if default_rm_user:
            source.default_rm_user_id = default_rm_user.id

        return source

    def create_portal_lead(self, **kwargs):
        """Helper with dynamic defaults."""
        values = {
            'name': 'Test Lead',
            'phone': '9876543210',
            'email': 'test@example.com',
            'source_id': self.source_magicbricks.id,
            'portal_property_id': self.mb_id, # Dynamic default
            'state': 'new'
        }
        values.update(kwargs)

        source_name = values.pop('source_name', False)
        portal_name = values.pop('portal_name', False)

        if source_name or portal_name:
            source = self.env['leads.new']._get_or_create_source(
                source_name or portal_name,
                source_type='portal',
            )
            values['source_id'] = source.id

            default_rm_map = {
                'MagicBricks': self.mayuri_user,
                '99acres': self.pratham_user,
                'Housing.com': self.naresh_user,
                'OLX': self.naresh_user,
                'UnknownPortal': self.naresh_user,
            }
            rm_user = default_rm_map.get(source_name or portal_name)
            if rm_user and source.default_rm_user_id != rm_user:
                source.sudo().write({'default_rm_user_id': rm_user.id})

        return self.env['leads.new'].with_context(
            automated_lead_creation=True,
        ).create(values)