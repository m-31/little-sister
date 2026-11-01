/* Maintenance click-popover (ADR-0019 machinery, ADR-0014 data).
 *
 * The band's **pill** opens the #maintenance-card popover, cloning the hidden
 * <template class="maintenance-pop-src" data-pop-for="__all__"> beside it: the whole
 * capped set, with a "+N more" to /handled. A card's own pip went with the door
 * (ADR-0147 decision 2): ◇ on its head counts what is handled at and beneath it.
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

    var current = null;   // the pill the popover is currently open for
    var cleanup = null;   // Floating UI autoUpdate teardown

    // The popover's source: the hidden <template> the pill's set is drawn in.
    function sourceFor() {
        return grid.querySelector('.maintenance-pop-src[data-pop-for="__all__"]');
    }

    function place(pill) {
        FUI.computePosition(pill, card, {
            strategy: "fixed",
            placement: "bottom-end",
            middleware: [FUI.offset(6), FUI.flip(), FUI.shift({ padding: 8 })]
        }).then(function (pos) {
            card.style.left = pos.x + "px";
            card.style.top = pos.y + "px";
        });
    }

    function open(pill) {
        var src = sourceFor();
        if (!src) { return; }
        card.innerHTML = src.innerHTML;
        card.hidden = false;
        current = pill;
        pill.setAttribute("aria-expanded", "true");
        if (cleanup) { cleanup(); }
        cleanup = FUI.autoUpdate(pill, card, function () { place(pill); });
    }

    function close() {
        if (!current) { return; }
        card.hidden = true;
        card.innerHTML = "";
        current.setAttribute("aria-expanded", "false");
        current = null;
        if (cleanup) { cleanup(); cleanup = null; }
    }

    // A click on the pill toggles its popover. stopPropagation keeps this click off
    // the document-level "click outside closes" handler below.
    grid.addEventListener("click", function (e) {
        var trigger = e.target.closest ? e.target.closest(".maintenance-pill") : null;
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

    // The ~10s poll replaces #status-grid's contents; if the open pill is swapped
    // out, drop the popover (its trigger is gone).
    new MutationObserver(function () {
        if (current && !grid.contains(current)) { close(); }
    }).observe(grid, { childList: true, subtree: true });
})();
