/** @odoo-module */

/**
 * WhatsApp interactive-list length caps, shared by every place that builds a
 * list: the chat composer's list builder and the quick-reply editor.
 *
 * Exceeding any of these makes Interakt reject the WHOLE message with a 400
 * ("'title' is a required string which maximum of 24 characters in each JSON of
 * 'rows' array"), so both editors cap input and block save/send.
 *
 * Mirrored server-side in wa_communication/models/wa_conversation_outbound.py
 * and on the platform in shared/interakt.py — keep the three in sync.
 */
export const WA_LIST_LIMITS = {
    button: 20,
    sectionTitle: 24,
    rowTitle: 24,
    rowDesc: 72,
    maxRows: 10,
};

/**
 * Return a ready-to-show error for the first over-long piece of list text, or
 * null when everything fits.
 *
 * We report rather than truncate: silently clipping "Liked & Want Another visit
 * with family" to 24 chars would ask the buyer a different question than the
 * author wrote.
 *
 * @param {String} button   the list button label
 * @param {Array}  sections [{title, rows: [{title, description}]}]
 * @returns {String|null}
 */
export function findOverLongListText(button, sections) {
    const L = WA_LIST_LIMITS;
    const btn = (button || "").trim();
    if (btn.length > L.button) {
        return `The button label is ${btn.length} characters — max ${L.button}.`;
    }
    for (const s of sections || []) {
        const sTitle = (s.title || "").trim();
        if (sTitle.length > L.sectionTitle) {
            return `Section title “${sTitle}” is ${sTitle.length} characters — max ${L.sectionTitle}.`;
        }
        for (const r of s.rows || []) {
            const title = (r.title || "").trim();
            if (title.length > L.rowTitle) {
                return `Item “${title}” is ${title.length} characters — max ${L.rowTitle}. Please shorten it.`;
            }
            const desc = (r.description || "").trim();
            if (desc.length > L.rowDesc) {
                return `The description for “${title}” is ${desc.length} characters — max ${L.rowDesc}.`;
            }
        }
    }
    return null;
}
