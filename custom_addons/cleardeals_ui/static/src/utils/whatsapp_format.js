/** @odoo-module */

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
 * Format a plain-text WhatsApp message into safe HTML.
 * @param {String} value
 * @returns {String} HTML string (already escaped + formatted)
 */
export function formatWhatsApp(value) {
    if (value === undefined || value === null) return "";
    let s = escapeHtml(value);
    // Monospace first (triple backticks), so inner * _ ~ are not reprocessed.
    s = s.replace(/```(?=\S)([\s\S]*?\S|\S)```/g, "<code>$1</code>");
    s = applyMarker(s, "*", "b");
    s = applyMarker(s, "_", "i");
    s = applyMarker(s, "~", "s");
    s = s.replace(/\r?\n/g, "<br/>");
    return s;
}
