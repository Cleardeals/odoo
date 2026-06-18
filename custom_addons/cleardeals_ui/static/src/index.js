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
export { CdMetricCard }              from "./components/metric_card/metric_card";
export { CdBarChart }                from "./components/bar_chart/bar_chart";

// ── chat components ──────────────────────────────────────────────────────────
export { CdWindowBadge }             from "./components/window_badge/window_badge";
export { CdChatBubble }              from "./components/chat_bubble/chat_bubble";
export { CdChatThread }              from "./components/chat_thread/chat_thread";
export { CdChatComposer }            from "./components/chat_composer/chat_composer";
export { CdConversationListItem }    from "./components/conversation_list_item/conversation_list_item";
export { CdQuickReplyPicker }        from "./components/quick_reply_picker/quick_reply_picker";
export { CdTemplatePickerModal }     from "./components/template_picker_modal/template_picker_modal";
export { CdInquirySwitcher }         from "./components/inquiry_switcher/inquiry_switcher";

// ── analytics primitives (redesigned dashboard) ──────────────────────────────
export { CdChart }                   from "./components/cd_chart/cd_chart";
export { CdKpiCard }                 from "./components/cd_kpi_card/cd_kpi_card";
export { CdWorklistPanel }           from "./components/cd_worklist_panel/cd_worklist_panel";
export { CdLeaderboardTable }        from "./components/cd_leaderboard_table/cd_leaderboard_table";
