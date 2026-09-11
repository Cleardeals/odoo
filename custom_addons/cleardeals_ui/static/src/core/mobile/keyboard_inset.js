/** @odoo-module */

import { onMounted, onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * Publish the on-screen keyboard's height as `--cd-kb` on the document root.
 *
 * The problem: on Android Chrome the keyboard shrinks the *visual* viewport but
 * leaves the *layout* viewport alone, so `100dvh` still measures the full
 * screen and the bottom of a viewport-height panel — our composer — ends up
 * underneath the keyboard. iOS behaves differently again. `visualViewport` is
 * the only thing that reports what is actually visible.
 *
 * Rather than reposition anything from JS, we publish the inset once and let
 * the stylesheets subtract it. That keeps the layout rules in the stylesheets
 * where they can be read, and means a surface opts in by using the variable.
 *
 * Safe by construction: the variable defaults to 0px, so a browser without
 * `visualViewport` (or a desktop, where this hook is not used) behaves exactly
 * as it did before.
 */
export function useKeyboardInset() {
    const root = () => browser.document?.documentElement;
    const vv = () => browser.visualViewport;

    const update = () => {
        const viewport = vv();
        const el = root();
        if (!viewport || !el) {
            return;
        }
        // What the keyboard covers: the gap between the layout viewport and the
        // visual one, minus however far the page is scrolled within it. Clamped
        // at 0 because pinch-zoom can make this negative.
        const covered = Math.max(
            0,
            browser.innerHeight - viewport.height - viewport.offsetTop,
        );
        // Ignore small deltas — browser chrome collapsing on scroll produces a
        // 40-60px change that is not a keyboard, and reacting to it makes the
        // thread jump while the RM is reading.
        el.style.setProperty("--cd-kb", covered > 120 ? `${Math.round(covered)}px` : "0px");
    };

    onMounted(() => {
        const viewport = vv();
        if (!viewport) {
            return;             // no visualViewport: leave --cd-kb at its default
        }
        viewport.addEventListener("resize", update);
        viewport.addEventListener("scroll", update);
        update();
    });

    onWillUnmount(() => {
        const viewport = vv();
        if (viewport) {
            viewport.removeEventListener("resize", update);
            viewport.removeEventListener("scroll", update);
        }
        root()?.style.removeProperty("--cd-kb");
    });
}
