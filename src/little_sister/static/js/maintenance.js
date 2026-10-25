/* Maintenance click-popover (ADR-0019 machinery, ADR-0014 data).
 *
 * Two triggers open the same #maintenance-card popover, each cloning a hidden
 * <template class="maintenance-pop-src"> keyed by data-pop-for: a card's **pip**, the
 * ringed diamond (keyed to its card path -> that subtree's pins), and the strip
 * **pill** (keyed "__all__" -> the whole capped set, with a "+N more" to /handled).
 * Bound once via event delegation on #status-grid, so it survives the ~10s grid
 * innerHTML swaps; positioned with Floating UI. Click the trigger again, click outside,
 * or Escape to close. A deliberate click, not a hover: an ambient reminder, opt-in
 * detail. The pill is an <a href="/handled">, so with no JS — or no Floating UI,
 * when this script early-returns below — it still reaches the full page; here a plain
 * click is upgraded to the popover, a modified click (new tab) left to the browser.
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    var card = document.getElementById("maintenance-card");
    if (!grid || !card || !window.FloatingUIDOM) { return; }
    var FUI = window.FloatingUIDOM;

    var current = null;   // the pip/pill trigger the popover is currently open for
    var cleanup = null;   // Floating UI autoUpdate teardown

    // The popover source is a hidden <template> keyed by data-pop-for: a card pip is
    // keyed to its card path (the pins under it), the strip pill to "__all__" (the
    // whole capped set).
    function sourceFor(trigger) {
        var key;
        if (trigger.classList.contains("maintenance-pill")) {
            key = "__all__";
        } else {
            var head = trigger.closest("[data-path]");
            if (!head) { return null; }
            key = head.getAttribute("data-path");
        }
        var esc = (window.CSS && CSS.escape) ? CSS.escape(key) : key;
        return grid.querySelector('.maintenance-pop-src[data-pop-for="' + esc + '"]');
    }

    function place(pip) {
        FUI.computePosition(pip, card, {
            strategy: "fixed",
            placement: "bottom-end",
            middleware: [FUI.offset(6), FUI.flip(), FUI.shift({ padding: 8 })]
        }).then(function (pos) {
            card.style.left = pos.x + "px";
            card.style.top = pos.y + "px";
        });
    }

    function open(pip) {
        var src = sourceFor(pip);
        if (!src) { return; }
        card.innerHTML = src.innerHTML;
        card.hidden = false;
        current = pip;
        pip.setAttribute("aria-expanded", "true");
        if (cleanup) { cleanup(); }
        cleanup = FUI.autoUpdate(pip, card, function () { place(pip); });
    }

    function close() {
        if (!current) { return; }
        card.hidden = true;
        card.innerHTML = "";
        current.setAttribute("aria-expanded", "false");
        current = null;
        if (cleanup) { cleanup(); cleanup = null; }
    }

    // A pip click toggles its popover. stopPropagation keeps this click off the
    // document-level "click outside closes" handler below (and off card navigation).
    grid.addEventListener("click", function (e) {
        var trigger = e.target.closest
            ? e.target.closest(".maintenance-pip, .maintenance-pill") : null;
        if (!trigger) { return; }
        // The pill is a link to /handled; leave a modified click (new tab/window)
        // to the browser so the full page still opens.
        if (e.metaKey || e.ctrlKey || e.shiftKey) { return; }
        e.preventDefault();
        e.stopPropagation();
        if (current === trigger) { close(); return; }
        close();
        open(trigger);
    });

    // Click anywhere outside the open popover closes it; a click inside (a pin link)
    // is left alone so it navigates.
    document.addEventListener("click", function (e) {
        if (!current) { return; }
        if (card.contains(e.target)) { return; }
        close();
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { close(); }
    });

    // The ~10s poll replaces #status-grid's contents; if the open pip is swapped out,
    // drop the popover (its trigger is gone).
    new MutationObserver(function () {
        if (current && !grid.contains(current)) { close(); }
    }).observe(grid, { childList: true, subtree: true });
})();
