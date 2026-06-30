{
    "name": "Deals Management",
    "version": "1.0.0",
    "depends": ["base", "web", "mail", "leads", "properties"],
    "author": "Vivek Shahi",
    "category": "Operations",
    "description": "Comprehensive deals management system for tracking and managing deal owners, their deal offers, and associated deal packages across properties.",
    "data": [
        # 1. Security
        "security/deals_security.xml",
        "security/ir.model.access.csv",
        # 2. Data (Sequences)
        "data/deal_sequences.xml",
        "data/deal_transaction_sequences.xml",
        # 3. Model Views
        "views/deal_owner_views.xml",
        "views/deal_offer_views.xml",
        "views/deal_package_views.xml",
        "views/deal_views.xml",
        "views/deal_transaction_views.xml",
        # 4. Menu Views
        "views/deal_menu.xml",
    ],
    "license": "LGPL-3",
}
