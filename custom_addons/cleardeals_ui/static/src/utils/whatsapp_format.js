/** @odoo-module */

import { markup } from "@odoo/owl";

/**
 * WhatsApp-style inline text formatting.
 *
 * Converts WhatsApp markdown into safe HTML for rendering message bubbles and
 * quick-reply previews:
 *   *bold*        -> <b>
 *   _italic_      -> <i>
 *   ~strike~      -> <s>
 *   ```mono```    -> <code>  (monospace)
 *   newlines      -> <br>
 *
 * The input is HTML-escaped FIRST, so the result is safe to inject with t-out.
 * Markers only fire when they wrap at least one non-space character, mirroring
 * WhatsApp's own behaviour (so a lone "*" or "5 * 3" is left untouched).
 *
 * Returns an OWL markup() object so that t-out renders the HTML instead of
 * escaping it. (Plain strings passed to t-out are still escaped in OWL 2.)
 */

/**
 * Wrap the current selection of a <textarea> (or <input>) with `marker` on both
 * sides (WhatsApp style). If nothing is selected, inserts a pair of markers and
 * places the caret between them. Returns the new full value; the caller is
 * responsible for pushing it into component state. Selection is restored async.
 *
 * @param {HTMLTextAreaElement|HTMLInputElement} el
 * @param {String} marker  e.g. "*", "_", "~", "```"
 * @returns {String} the updated value
 */
export function wrapSelection(el, marker) {
    if (!el) return "";
    const value = el.value ?? "";
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const selected = value.slice(start, end);
    const next = value.slice(0, start) + marker + selected + marker + value.slice(end);
    // Restore a sensible selection/caret after the DOM updates.
    const caretStart = start + marker.length;
    const caretEnd = caretStart + selected.length;
    requestAnimationFrame(() => {
        el.focus();
        try { el.setSelectionRange(caretStart, caretEnd); } catch (_) {}
    });
    return next;
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/**
 * Apply one paired marker (e.g. "*" -> <b>) to already-escaped text.
 * `marker` is the literal delimiter; `tag` is the HTML tag name.
 */
function applyMarker(text, marker, tag) {
    // Escape the marker for use in a RegExp.
    const m = marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    // Wrap content that does not start/end with whitespace and has no marker inside.
    const re = new RegExp(`${m}(?=\\S)([^${m}]*?\\S|\\S)${m}`, "g");
    return text.replace(re, `<${tag}>$1</${tag}>`);
}

/**
 * Format a plain-text WhatsApp message into a safe HTML *string* (no markup wrapper).
 * Useful when callers need to further process the HTML (e.g. add search highlights)
 * before wrapping with markup().
 *
 * @param {String} value
 * @returns {String} Plain HTML string — NOT safe to inject as-is without markup().
 */
export function formatWhatsAppHtml(value) {
    if (value === undefined || value === null) return "";
    let s = String(value);
    // Normalise literal <br/> / <br> tags (platform may store them this way).
    s = s.replace(/<br\s*\/?>/gi, "\n");
    s = escapeHtml(s);
    s = s.replace(/```(?=\S)([\s\S]*?\S|\S)```/g, "<code>$1</code>");
    s = applyMarker(s, "*", "b");
    s = applyMarker(s, "_", "i");
    s = applyMarker(s, "~", "s");
    s = s.replace(/\r?\n/g, "<br/>");
    return s;
}

/**
 * Format a plain-text WhatsApp message into safe HTML wrapped in OWL markup().
 * Use with t-out.  (Plain strings passed to t-out are still escaped in OWL 2.)
 *
 * @param {String} value
 * @returns {markup}
 */
export function formatWhatsApp(value) {
    return markup(formatWhatsAppHtml(value));
}

/**
 * Wrap all occurrences of `query` inside an HTML string with
 * <mark class="cd-search-highlight">…</mark>, touching only text nodes
 * (content between > and <) so HTML tag attributes are never corrupted.
 *
 * Used by the in-chat search to highlight the exact phrase within a bubble.
 *
 * @param {String} html   The innerHTML produced by formatWhatsApp.
 * @param {String} query  Plain-text search term.
 * @returns {String}      HTML string with marks inserted.
 */
export function highlightHtml(html, query) {
    if (!query || !html) return html;
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(${escaped})`, "gi");
    // Walk segments: HTML tags are passed through; text nodes get the marks.
    return html.replace(/(<[^>]*>)|([^<]+)/g, (match, tag, text) => {
        if (tag) return tag;
        return text.replace(re, `<mark class="cd-search-highlight">$1</mark>`);
    });
}
