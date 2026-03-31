# Interaction Patterns

Complete, working patterns for every Odoo UI element.
Every pattern reflects the Cleardeals codebase conventions.

---

## The canonical form view

```xml
<record id="view_leads_new_form" model="ir.ui.view">
    <field name="name">leads.new.form</field>
    <field name="model">leads.new</field>
    <field name="arch" type="xml">
        <form string="Lead">

            <!-- HEADER: state progression + manager actions -->
            <header>
                <button name="action_manual_sync"
                        string="Sync from API"
                        type="object"
                        class="btn-secondary"
                        groups="properties.group_property_manager"/>
                <field name="state"
                       widget="statusbar"
                       statusbar_visible="new,assigned,failed"/>
            </header>

            <sheet>

                <!-- SMART BUTTONS: counts of related records -->
                <div class="oe_button_box" name="button_box">
                    <button name="action_view_related_leads"
                            type="object"
                            class="oe_stat_button"
                            icon="fa-phone">
                        <field name="related_lead_count"
                               widget="statinfo"
                               string="Related"/>
                    </button>
                </div>

                <!-- CONTEXTUAL BANNER: only when time-sensitive -->
                <div class="alert alert-info mb-0"
                     role="alert"
                     invisible="not is_ops_sale_lead">
                    <strong>Ops Sale Lead</strong> — this lead is flagged for
                    the operations sales team.
                </div>

                <!-- PRIMARY IDENTITY: what is this record? -->
                <div class="oe_title">
                    <h1>
                        <field name="name" placeholder="Lead name"/>
                    </h1>
                </div>

                <!-- LEVEL 1: always visible, primary task fields -->
                <group>
                    <group string="Contact">
                        <!-- WhatsApp HTML field: phone + clickable link -->
                        <field name="phone_whatsapp_html"
                               string="Phone"
                               widget="html"
                               readonly="1"
                               sanitize="0"/>
                        <field name="email" widget="email"/>
                        <field name="source"
                               string="Source"
                               readonly="portal_property_id != False"
                               placeholder="e.g. Walk-in, Referral, IVR"/>
                    </group>
                    <group string="Status">
                        <field name="current_status"/>
                        <field name="user_id" string="Assigned RM"/>
                        <field name="first_contact_datetime"
                               readonly="1"
                               string="First Contact"/>
                    </group>
                </group>

                <!-- REMARKS: always visible, always editable for RMs -->
                <group>
                    <field name="remarks"
                           placeholder="Add remarks about this lead..."
                           nolabel="1"/>
                </group>

                <!-- CONDITIONAL: site visit fields appear only when relevant -->
                <group string="Site Visit"
                       invisible="current_status not in (
                           'site_visit_scheduled',
                           'site_visit_done',
                           'rescheduled'
                       )">
                    <field name="site_visit_date"/>
                    <field name="feedback_site_visit_done"
                           invisible="current_status != 'site_visit_done'"/>
                </group>

                <!-- LEVEL 2: primary property -->
                <group string="Property">
                    <field name="property_base_id"
                           string="Property"
                           context="{'search_all_properties_for_lead': True}"
                           options="{'no_create': True}"/>
                    <field name="base_property_bhk"
                           string="BHK"
                           readonly="1"/>
                    <field name="base_property_location"
                           string="Location"
                           readonly="1"/>
                    <field name="base_property_link"
                           string="Property Link"
                           readonly="1"
                           widget="url"/>
                </group>

                <!-- LEVEL 3: tabs for sub-tasks -->
                <notebook>

                    <page string="Recommended Properties">
                        <field name="interest_ids" nolabel="1">
                            <list editable="bottom">
                                <field name="property_base_id"
                                       string="Property"
                                       context="{'search_all_properties_for_lead': True}"
                                       options="{'no_create': True, 'no_open': True}"/>
                                <field name="base_property_bhk"
                                       string="BHK"
                                       readonly="1"/>
                                <field name="base_property_location"
                                       string="Location"
                                       readonly="1"/>
                                <field name="current_status" string="Status"/>
                                <field name="site_visit_date"
                                       string="Site Visit"/>
                                <field name="remarks" string="Remarks"/>
                            </list>
                        </field>
                    </page>

                    <!-- Manager-only: internal data -->
                    <page string="Internal"
                          groups="properties.group_property_manager">
                        <group>
                            <field name="portal_property_id"
                                   string="Portal Listing ID"
                                   readonly="1"/>
                            <field name="portal_name"
                                   string="Portal"
                                   readonly="1"/>
                            <field name="project_name"
                                   string="Project"
                                   readonly="1"/>
                        </group>
                        <field name="process_notes"
                               string="Processing Notes"
                               readonly="1"/>
                        <field name="raw_data"
                               string="Raw Data"
                               readonly="1"/>
                    </page>

                </notebook>
            </sheet>
            <chatter/>
        </form>
    </field>
</record>
```

---

## The canonical list view

```xml
<record id="view_leads_new_list" model="ir.ui.view">
    <field name="name">leads.new.list</field>
    <field name="model">leads.new</field>
    <field name="arch" type="xml">
        <list string="Leads"
              default_order="create_date desc"
              decoration-danger="state == 'new'"
              decoration-success="state == 'assigned'"
              decoration-muted="state == 'failed'">

            <!-- Manager bulk actions -->
            <header>
                <button name="action_bulk_assign"
                        string="Assign to RM"
                        type="object"
                        groups="properties.group_property_manager"/>
            </header>

            <!-- Core columns: always visible, manager scans these -->
            <field name="name" string="Lead"/>
            <field name="phone"/>
            <field name="current_status" string="Status"/>
            <field name="user_id" string="RM"/>
            <field name="base_property_tag" string="Property"/>

            <!-- Optional columns: visible by user preference -->
            <field name="base_property_city"
                   string="City"
                   optional="hide"/>
            <field name="source"
                   string="Source"
                   optional="hide"/>
            <field name="site_visit_date_only"
                   string="Site Visit"
                   optional="hide"/>
            <field name="first_contact_datetime"
                   string="First Contact"
                   optional="hide"/>

            <!-- Date column: always useful -->
            <field name="create_date_only" string="Created"/>

            <!-- Invisible: needed for decoration only, not displayed -->
            <field name="state" column_invisible="1"/>
            <field name="is_webhook_sent" column_invisible="1"/>
        </list>
    </field>
</record>
```

---

## The canonical search view

```xml
<record id="view_leads_new_search" model="ir.ui.view">
    <field name="name">leads.new.search</field>
    <field name="model">leads.new</field>
    <field name="arch" type="xml">
        <search string="Search Leads">

            <!-- Primary fields: what users type to find records -->
            <field name="name" string="Lead Name"/>
            <field name="phone"/>
            <field name="user_id" string="RM"/>
            <field name="base_property_tag" string="Property"/>

            <!-- Relational search: through One2many -->
            <field name="portal_listing_ids"
                   string="Portal Listing ID"
                   filter_domain="[('portal_listing_ids.portal_listing_id',
                                    'ilike', self)]"/>

            <!-- User's own leads -->
            <filter name="my_leads"
                    string="My Leads"
                    domain="[('user_id', '=', uid)]"/>
            <separator/>

            <!-- Pipeline state filters -->
            <filter name="unassigned"
                    string="Unassigned"
                    domain="[('state', '=', 'new')]"/>
            <filter name="assigned"
                    string="Assigned"
                    domain="[('state', '=', 'assigned')]"/>
            <filter name="failed"
                    string="Failed"
                    domain="[('state', '=', 'failed')]"/>
            <separator/>

            <!-- Action-oriented filters: answers real manager questions -->
            <filter name="site_visit_today"
                    string="Site Visit Today"
                    domain="[('site_visit_date_only', '=',
                               context_today().strftime('%Y-%m-%d'))]"/>
            <filter name="never_contacted"
                    string="Never Contacted"
                    domain="[('first_contact_datetime', '=', False),
                             ('state', '=', 'assigned')]"/>
            <filter name="not_sent_webhook"
                    string="Pending n8n Dispatch"
                    domain="[('is_webhook_sent', '=', False)]"
                    groups="properties.group_property_manager"/>
            <separator/>

            <!-- Time-based filters -->
            <filter name="created_today"
                    string="Created Today"
                    domain="[('create_date_only', '=',
                               context_today().strftime('%Y-%m-%d'))]"/>
            <filter name="this_week"
                    string="This Week"
                    domain="[('create_date', '>=',
                               (context_today() - datetime.timedelta(days=7))
                               .strftime('%Y-%m-%d'))]"/>

            <!-- Group by options -->
            <group>
                <filter name="group_rm"
                        string="RM"
                        context="{'group_by': 'user_id'}"/>
                <filter name="group_status"
                        string="Status"
                        context="{'group_by': 'current_status'}"/>
                <filter name="group_source"
                        string="Source"
                        context="{'group_by': 'source'}"/>
                <filter name="group_city"
                        string="City"
                        context="{'group_by': 'base_property_city'}"/>
                <filter name="group_created"
                        string="Created Date"
                        context="{'group_by': 'create_date_only:day'}"/>
            </group>

        </search>
    </field>
</record>
```

---

## Separate actions per user role

Never use one action for all users. Create dedicated actions with
context defaults shaped for each user's actual task:

```xml
<!-- RM action: my leads, assigned state -->
<record id="action_my_leads" model="ir.actions.act_window">
    <field name="name">My Leads</field>
    <field name="res_model">leads.new</field>
    <field name="view_mode">list,form,kanban</field>
    <field name="search_view_id" ref="view_leads_new_search"/>
    <field name="context">{
        'search_default_my_leads': 1,
        'search_default_assigned': 1
    }</field>
    <field name="help" type="html">
        <p class="o_view_nocontent_smiling_face">No leads assigned to you.</p>
        <p>New leads from portals are assigned automatically.
           Create a lead manually for walk-ins and referrals.</p>
    </field>
</record>

<!-- Manager action: all leads, grouped by RM -->
<record id="action_all_leads_manager" model="ir.actions.act_window">
    <field name="name">All Leads</field>
    <field name="res_model">leads.new</field>
    <field name="view_mode">list,kanban,form</field>
    <field name="search_view_id" ref="view_leads_new_search"/>
    <field name="context">{'search_default_group_rm': 1}</field>
    <field name="groups_id"
           eval="[(4, ref('properties.group_property_manager'))]"/>
</record>

<!-- Manager action: unassigned leads requiring attention -->
<record id="action_unassigned_leads" model="ir.actions.act_window">
    <field name="name">Unassigned Leads</field>
    <field name="res_model">leads.new</field>
    <field name="view_mode">list,form</field>
    <field name="domain">[('state', '=', 'new')]</field>
    <field name="context">{'search_default_group_created': 1}</field>
    <field name="groups_id"
           eval="[(4, ref('properties.group_property_manager'))]"/>
</record>
```

---

## Performance rules — the non-negotiables

```
RULE 1: No One2many fields as list view columns
  Bad:  <field name="interest_ids"/>  in a list view
  Good: <field name="interest_count"/> (computed Integer, store=True)

RULE 2: Every action must have a default filter
  Bad:  <field name="context">{}</field>  — loads all records
  Good: <field name="context">{'search_default_my_leads': 1}</field>

RULE 3: column_invisible for decoration-only fields
  Bad:  leave state visible when only used for decoration-danger
  Good: <field name="state" column_invisible="1"/>

RULE 4: optional="hide" for rarely-used columns
  Every column a manager uses < 50% of the time: optional="hide"
  Let the user choose to show it. Default to the minimum useful set.

RULE 5: store=True only when filtered/sorted/grouped on
  A store=True computed field is a write cost on every dependency change.
  Only pay that cost if the field is actually used in a domain or order.
```