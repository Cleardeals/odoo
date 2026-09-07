/** @odoo-module */

/**
 * Datetime helpers for WhatsApp UIs.
 *
 * Odoo serializes datetimes over RPC as naive strings in **UTC** with no
 * timezone marker, e.g. "2026-06-02 08:50:03".  `new Date("2026-06-02 08:50:03")`
 * parses that as *local* time, so a browser already in IST reads 08:50 as IST
 * and any later `timeZone: "Asia/Kolkata"` formatting becomes a no-op (the bug
 * where everything shows UTC).  Likewise a 24h window countdown is short by the
 * local UTC offset (24h − 5.5h = "18h 29m").
 *
 * `parseServerDateTime` normalises the string to an unambiguous UTC instant so
 * every downstream `toLocaleString({ timeZone })` / arithmetic is correct.
 */

const IST = "Asia/Kolkata";

/**
 * Parse an Odoo server datetime string (UTC, naive) into a Date.
 * Accepts already-ISO strings (with "T"/"Z") and passes them through.
 * Returns null for falsy input.
 */
export function parseServerDateTime(value) {
    if (!value) return null;
    if (value instanceof Date) return value;
    let s = String(value).trim();
    // Already carries explicit tz info (Z or ±hh:mm) → trust it.
    if (/[zZ]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s)) {
        return new Date(s.replace(" ", "T"));
    }
    // Naive "YYYY-MM-DD HH:MM:SS" → treat as UTC.
    return new Date(s.replace(" ", "T") + "Z");
}

/** "08:50" style time-of-day in IST. */
export function formatISTTime(value) {
    const d = parseServerDateTime(value);
    if (!d || isNaN(d)) return "";
    return d.toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: IST,
    });
}

/** "2 Jun, 08:50" style date+time in IST. */
export function formatISTDateTime(value) {
    const d = parseServerDateTime(value);
    if (!d || isNaN(d)) return "";
    return d.toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: IST,
    });
}

/** Stable per-day key in IST, e.g. "2026-06-04", for grouping messages by date. */
export function istDayKey(value) {
    const d = parseServerDateTime(value);
    if (!d || isNaN(d)) return "";
    // en-CA yields ISO-style YYYY-MM-DD.
    return d.toLocaleDateString("en-CA", { timeZone: IST });
}

/**
 * WhatsApp-style day separator label in IST:
 *   "Today" / "Yesterday" / "4 June 2026".
 */
export function formatDayLabel(value) {
    const d = parseServerDateTime(value);
    if (!d || isNaN(d)) return "";
    const key = istDayKey(value);
    const now = new Date();
    const todayKey = now.toLocaleDateString("en-CA", { timeZone: IST });
    const yest = new Date(now.getTime() - 86400000);
    const yestKey = yest.toLocaleDateString("en-CA", { timeZone: IST });
    if (key === todayKey) return "Today";
    if (key === yestKey) return "Yesterday";
    return d.toLocaleDateString("en-IN", {
        day: "numeric", month: "long", year: "numeric", timeZone: IST,
    });
}

/** Coarse "5m ago" / "3h ago" / "2 Jun" relative label. */
export function relativeTime(value) {
    const d = parseServerDateTime(value);
    if (!d || isNaN(d)) return "";
    const diffMin = (Date.now() - d.getTime()) / 60_000;
    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${Math.round(diffMin)}m ago`;
    if (diffMin < 1440) return `${Math.round(diffMin / 60)}h ago`;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: IST });
}
