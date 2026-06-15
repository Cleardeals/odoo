{
    "name": "Deals Management",
    "version": "1.0.0",
    "depends": ["base", "web", "mail"],
    "author": "Vivek Shahi",
    "category": "Operations",
    "description": "Comprehensive deals management system for tracking and managing deal owners, their deal offers, and associated deal packages across properties.",
    "data": [
        # 1. Security (Always First)
        "security/ir.model.access.csv",
        # 2. Menu Views
        "views/deal_owner_menu.xml",
        "views/deal_offer_menu.xml",
        "views/deal_package_menu.xml",
        # 3. Model Views
        "views/deal_owner_views.xml",
        "views/deal_offer_views.xml",
        "views/deal_package_views.xml",
    ],
}
