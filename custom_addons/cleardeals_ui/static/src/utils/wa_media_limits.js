/** @odoo-module */

/**
 * WhatsApp media size caps (Meta Cloud API limits), in bytes.
 *
 * Checked in the browser BEFORE the upload starts, so an oversized file never
 * leaves the machine — the server enforces the same caps again (see
 * wa_communication/controllers/media_upload.py), but by then the bytes have
 * already been transferred.
 *
 * Mirrored server-side in wa_communication/models/wa_conversation_outbound.py —
 * keep the two in sync.
 */
export const WA_MEDIA_LIMITS = {
    image: 5 * 1024 * 1024,
    video: 16 * 1024 * 1024,
    audio: 16 * 1024 * 1024,
    document: 100 * 1024 * 1024,
};

/** Mime prefixes WhatsApp refuses for the Document type. */
const DOCUMENT_FORBIDDEN_PREFIXES = ["video/", "image/", "audio/"];

export function waFormatBytes(n) {
    const mb = (n || 0) / (1024 * 1024);
    return mb >= 0.1 ? `${mb.toFixed(1)} MB` : `${Math.round((n || 0) / 1024)} KB`;
}

export function waMediaCap(kind) {
    return WA_MEDIA_LIMITS[(kind || "document").toLowerCase()] || WA_MEDIA_LIMITS.document;
}

/**
 * Return a user-facing error for a file WhatsApp would refuse, or null.
 *
 * @param {String} kind  "image" | "video" | "audio" | "document"
 * @param {File}   file  the browser File object
 */
export function checkMediaFile(kind, file) {
    const k = (kind || "document").toLowerCase();
    const type = (file.type || "").toLowerCase();
    if (k === "document" && DOCUMENT_FORBIDDEN_PREFIXES.some((p) => type.startsWith(p))) {
        const real = type.split("/")[0];
        return `“${file.name}” is a ${real} file — WhatsApp does not accept it as a Document. Use the ${real} button instead.`;
    }
    const cap = waMediaCap(k);
    if (file.size > cap) {
        return `“${file.name}” is ${waFormatBytes(file.size)} — WhatsApp allows at most ${waFormatBytes(cap)} for a ${k}. Please compress it or share a link instead.`;
    }
    return null;
}
