/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

// This is the main function that Odoo will call
async function whatsappWithCopyAction(env, action) {
    const { whatsapp_url, message_text } = action.context;
    const notificationService = env.services.notification; // Get Odoo's notification service

    if (!message_text || !whatsapp_url) {
        return;
    }

    // --- Clipboard API with Fallback ---
    // This is robust: it tries the new way, then the old way.
    // This is needed because you are on http://localhost

    let copied = false;
    if (navigator.clipboard && window.isSecureContext) {
        // Modern, secure method (for HTTPS or localhost)
        try {
            await navigator.clipboard.writeText(message_text);
            copied = true;
        } catch (err) {
            console.error("Failed to copy using navigator.clipboard:", err);
        }
    } 

    if (!copied) {
        // Fallback method (for insecure HTTP)
        try {
            var textArea = document.createElement("textarea");
            textArea.value = message_text;
            textArea.style.position = "fixed";  // Hide it
            textArea.style.top = 0;
            textArea.style.left = 0;
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            document.execCommand('copy'); // This is the old, but reliable command
            document.body.removeChild(textArea);
            copied = true;
        } catch (err) {
            console.error("Failed to copy using fallback execCommand:", err);
        }
    }

    // --- Step 2: Show Odoo Notification ---
    if (copied) {
        notificationService.add(
            _t("Message copied to clipboard!"), 
            { type: "success" } // 'success', 'warning', 'danger', 'info'
        );
    } else {
        notificationService.add(
            _t("Failed to copy message. Please copy it manually."), 
            { type: "danger" }
        );
    }

    // --- Step 3: Open the WhatsApp Link ---
    // We open the link *after* the copy is done.
    window.open(whatsapp_url, '_self');
}

// This registers our function with Odoo's client action registry
// The tag 'whatsapp_with_copy' must match the 'tag' in your Python code.
registry.category("actions").add("whatsapp_with_copy", whatsappWithCopyAction);