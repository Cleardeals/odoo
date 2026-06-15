{
    'name': 'Cleardeals UI',
    'version': '1.0.2',
    'summary': 'Central OWL component library for all Cleardeals custom addons.',
    'description': """
Central OWL component library for Cleardeals.

All reusable frontend components live here. Other custom addons declare
``cleardeals_ui`` as a dependency and reference components by their registry
key or import path — they never define their own UI primitives.

Directory layout mirrors Odoo's own ``web`` addon:

``static/src/core/``
    Generic UI primitives (no field binding): pills, cards, banners, etc.
    Analogous to ``addons/web/static/src/core/``.

``static/src/fields/``
    Field widgets registered to the ``fields`` registry.  Used via
    ``widget="cd_*"`` in XML views.
    Analogous to ``addons/web/static/src/views/fields/``.

``static/src/widgets/``
    Standalone view widgets registered to the ``view_widgets`` registry.
    Used via ``<widget name="cd_*"/>`` in XML views (no field backing).

Adding a new component
----------------------
1. Create a sub-directory under the appropriate category above.
2. Add three files: ``<name>.js``, ``<name>.xml``, ``<name>.scss``.
3. Export the class and descriptor from ``<name>.js``; call
   ``registry.category(...).add(...)`` at module level.
4. Re-export from ``static/src/index.js`` so other modules can import it.
5. The ``**/*.js`` / ``**/*.xml`` / ``**/*.scss`` globs in the assets block
   below pick up the new files automatically — no manifest edit required.
    """,
    'author': 'Cleardeals Technology',
    'category': 'Technical',
    'license': 'LGPL-3',
    'depends': ['web', 'cleardeals_notification'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'cleardeals_ui/static/src/**/*.js',
            'cleardeals_ui/static/src/**/*.xml',
            'cleardeals_ui/static/src/**/*.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
