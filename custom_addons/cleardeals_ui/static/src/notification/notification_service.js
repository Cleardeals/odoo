/** @odoo-module */

/**
 * cd_notification — the central, app-wide notification service.
 *
 * Responsibilities:
 *  - subscribe to the per-user bus channel `cleardeals_notification_{uid}` and
 *    receive `cd_notification` events from ANY module's
 *    `cleardeals.notification.notify(...)` call;
 *  - on startup, pull persisted unread notifications (`get_unread`) so anything
 *    raised while the user was offline / on another screen is recovered — never
 *    lost (delivery is compulsory);
 *  - keep a single reactive store the popup stack AND the systray bell both read;
 *  - suppress only the *popup* (not the history entry) when the user is already
 *    looking at the matching context — e.g. that exact WA chat. A caller sets
 *    `payload.suppress_key`; the viewing component calls `setActiveSuppressKey`.
 *
 * It is WhatsApp-agnostic: types, icons, and actions come from the
 * `cd_notification_types` registry (see notification_config.js).
 */

import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";
import { getNotifConfig } from "./notification_config";

const MODEL = "cleardeals.notification";
const POPUP_DISMISS_MS = 8000;
const MAX_POPUPS = 5;

export const cdNotificationService = {
    dependencies: ["bus_service", "orm", "notification", "action"],

    start(env, { bus_service, orm, notification, action }) {
        const state = reactive({
            items: [],          // full history (unread + recently-read), newest first
            popups: [],         // subset currently shown as toasts
            unreadCount: 0,
            activeSuppressKey: null,
        });
        const timers = {};

        const recount = () => {
            state.unreadCount = state.items.filter((n) => !n.is_read).length;
        };

        const upsert = (n) => {
            const i = state.items.findIndex(
                (x) => x.notification_id === n.notification_id
            );
            if (i >= 0) {
                Object.assign(state.items[i], n);
            } else {
                state.items.unshift(n);
            }
            recount();
        };

        const removePopup = (id) => {
            if (timers[id]) {
                browser.clearTimeout(timers[id]);
                delete timers[id];
            }
            state.popups = state.popups.filter((p) => p.notification_id !== id);
        };

        const showPopup = (n) => {
            if (state.popups.some((p) => p.notification_id === n.notification_id)) {
                return;
            }
            state.popups = [n, ...state.popups].slice(0, MAX_POPUPS);
            // Actionable/sticky popups persist until the user acts; others fade.
            if (!n.actionable && !n.sticky) {
                timers[n.notification_id] = browser.setTimeout(
                    () => removePopup(n.notification_id),
                    POPUP_DISMISS_MS
                );
            }
        };

        const onEvent = (payload) => {
            upsert(payload);
            const suppressed =
                payload.suppress_key &&
                payload.suppress_key === state.activeSuppressKey;
            if (!suppressed && !payload.is_read) {
                showPopup(payload);
            }
        };

        async function loadPersisted() {
            try {
                const list = await orm.call(MODEL, "get_unread", []);
                // Oldest first so unshift leaves newest at the top.
                for (const n of list.slice().reverse()) {
                    upsert(n);
                }
            } catch {
                // Model may not be installed in some DBs — degrade silently.
            }
        }

        const uid = session.uid;
        if (uid) {
            bus_service.subscribe("cd_notification", onEvent);
            bus_service.addChannel(`cleardeals_notification_${uid}`);
            loadPersisted();
        }

        async function markRead(id) {
            const n = state.items.find((x) => x.notification_id === id);
            if (n && !n.is_read) {
                n.is_read = true;
                recount();
            }
            removePopup(id);
            try {
                await orm.call(MODEL, "mark_read", [[id]]);
            } catch {
                /* best-effort */
            }
        }

        async function markAllRead() {
            state.items.forEach((n) => (n.is_read = true));
            recount();
            state.popups = [];
            try {
                await orm.call(MODEL, "mark_all_read", []);
            } catch {
                /* best-effort */
            }
        }

        /** Run a declarative action (Approve/Decline/…) from the type config. */
        async function executeAction(notif, act) {
            try {
                await orm.call(act.model, act.method, act.args ? act.args(notif) : [[notif.notification_id]]);
                if (act.okMessage) {
                    notification.add(act.okMessage, { type: act.okType || "success" });
                }
                await markRead(notif.notification_id);
            } catch (e) {
                notification.add(
                    e.data?.message || act.errMessage || "Action failed.",
                    { type: "danger" }
                );
            }
        }

        /** Click-through navigation for a non-actionable notification. */
        function open(notif) {
            const cfg = getNotifConfig(notif.type);
            if (cfg.open && cfg.open.model) {
                const resId = cfg.open.resId ? cfg.open.resId(notif) : notif.res_id;
                if (resId) {
                    action.doAction({
                        type: "ir.actions.act_window",
                        res_model: cfg.open.model,
                        res_id: resId,
                        views: [[false, "form"]],
                        target: "current",
                    });
                }
            }
            markRead(notif.notification_id);
        }

        return {
            state,
            getConfig: getNotifConfig,
            markRead,
            markAllRead,
            removePopup,
            executeAction,
            open,
            setActiveSuppressKey: (k) => {
                state.activeSuppressKey = k || null;
            },
            clearActiveSuppressKey: () => {
                state.activeSuppressKey = null;
            },
        };
    },
};

registry.category("services").add("cd_notification", cdNotificationService);
