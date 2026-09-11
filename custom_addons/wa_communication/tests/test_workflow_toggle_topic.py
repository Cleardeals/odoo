"""Workflow toggle publish — topic name is built from ``GCP_ENV``.

``wa.workflow`` reaches the workflow-control topic through a config parameter
that stores a bare ALIAS (``workflow-control``); the ``cd-<env>-`` prefix is
assembled at publish time from the ``GCP_ENV`` environment variable.

That indirection hid a production outage in waiting.  ``GCP_ENV`` was set on
stage and unset on production, so production would have resolved the topic to
``cd-local-workflow-control`` — a topic that does not exist — inside a caught
exception on a post-commit callback.  The visible behaviour: an operator pauses
a workflow, Odoo agrees it is paused, and the platform keeps messaging
customers.  Nothing in the UI or the tests said otherwise.

These tests pin the mapping so a missing or renamed environment cannot go
unnoticed again.
"""

import os
from unittest.mock import patch

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestWorkflowTogglePubsubTopic(WaTransactionCase):

    def setUp(self):
        super().setUp()
        self.workflow = self.env['wa.workflow'].create({
            'slug': 'topic_probe_v1',
            'name': 'Topic Probe',
            'is_active': False,
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.topic_workflow_control', 'workflow-control')

    def _topic_published_with(self, gcp_env):
        """Toggle the workflow under *gcp_env* and return the topic used.

        The publish is deferred to a post-commit callback, which the test
        cursor never runs on its own — it has to be driven explicitly.
        """
        seen = []

        # Patched onto the class, so the bound `self` arrives as the first
        # argument. The model swallows any exception from this callback, which
        # would turn a signature mistake here into an empty list and a
        # misleading failure rather than an error.
        def _capture(_model_self, topic, payload):
            seen.append(topic)

        env_patch = patch.dict(os.environ, {} if gcp_env is None else {'GCP_ENV': gcp_env})
        if gcp_env is None:
            env_patch = patch.dict(os.environ)

        with env_patch:
            if gcp_env is None:
                os.environ.pop('GCP_ENV', None)
            with patch.object(
                type(self.env['cleardeals.pubsub']), 'publish_async', _capture
            ):
                self.workflow.action_toggle_active()
                self.env.cr.postcommit.run()

        return seen

    def test_production_env_targets_the_prod_topic(self):
        self.assertEqual(
            self._topic_published_with('production'), ['cd-prod-workflow-control'])

    def test_staging_env_targets_the_staging_topic(self):
        self.assertEqual(
            self._topic_published_with('staging'), ['cd-staging-workflow-control'])

    def test_unset_env_falls_back_to_local_and_never_to_prod(self):
        """An unset GCP_ENV must not silently reach production topics."""
        topics = self._topic_published_with(None)
        self.assertEqual(topics, ['cd-local-workflow-control'])
        self.assertNotIn('cd-prod-workflow-control', topics)
