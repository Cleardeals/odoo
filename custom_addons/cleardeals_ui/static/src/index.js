/**
 * cleardeals_ui — central component library index
 *
 * Re-exports every public component, field widget, and view widget from this
 * addon so other modules can import them by name:
 *
 *   import { CdStatusBadge } from "@cleardeals_ui/index";
 *
 * Registration side-effects (registry.category(...).add(...)) live in each
 * component file and run when those modules are first imported.  The asset
 * bundle globs in __manifest__.py load all files automatically, so no entry
 * needs to be added here purely to trigger registration — only add exports
 * that other JS modules will import by name.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * Sections mirror the directory layout:
 *
 *   core/    → generic UI primitives  (no registry, pure components)
 *   fields/  → field widgets          (fields registry, widget="cd_*")
 *   widgets/ → standalone view widgets (view_widgets registry, <widget name="cd_*"/>)
 * ─────────────────────────────────────────────────────────────────────────────
 */

// ── fields ──────────────────────────────────────────────────────────────────
export { CdStatusBadge, cdStatusBadgeField } from "./fields/status_badge/status_badge";

// ── components ──────────────────────────────────────────────────────────────
export { CdMetricCard }            from "./components/metric_card/metric_card";
export { CdWorkflowHealthTable }   from "./components/workflow_health_table/workflow_health_table";
export { CdBarChart }              from "./components/bar_chart/bar_chart";
export { CdLineChart }             from "./components/line_chart/line_chart";
export { CdRecentFailuresTable }   from "./components/recent_failures_table/recent_failures_table";
