/* Inspection popover (ADR-0019).
 *
 * A custom hover card showing a node's static metadata (title / about /
 * description), preloaded with the page in #node-meta and rendered client-side.
 * Bound once via event delegation on #status-grid, so it survives the ~10s grid
 * innerHTML swaps. Positioned with Floating UI. The node stays a link to its
 * detail page; the card opens on hover / focus, stays open when the pointer
 * moves into it, and closes on leave / blur / Escape (tap to open on touch).
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    var card = document.getElementById("inspect-card");
    var dataEl = document.getElementById("node-meta");
    if (!grid || !card || !dataEl || !window.FloatingUIDOM) { return; }

    var META;
    try { META = JSON.parse(dataEl.textContent || "{}"); } catch (e) { return; }
    var FUI = window.FloatingUIDOM;

    var current = null;            // the trigger the card is currently shown for
    var cleanup = null;            // Floating UI autoUpdate teardown
    var showTimer = null, hideTimer = null;
    var lastPointerType = "mouse";

    function metaFor(el) {
        var t = el && el.closest ? el.closest("[data-path]") : null;
        if (!t) { return null; }
        var m = META[t.getAttribute("data-path")];
        return m ? { trigger: t, meta: m } : null;
    }

    function cardHtml(m) {
        var parts = [];
        if (m.title) {
            parts.push('<div class="inspect-card__title md-body">' + m.title + "</div>");
        }
        if (m.about) {
            parts.push('<div class="inspect-card__about md-body">' + m.about + "</div>");
        }
        return parts.join("");
    }

    function place(trigger) {
        FUI.computePosition(trigger, card, {
            strategy: "fixed",
            placement: "top",
            middleware: [FUI.offset(8), FUI.flip(), FUI.shift({ padding: 8 })]
        }).then(function (pos) {
            card.style.left = pos.x + "px";
            card.style.top = pos.y + "px";
        });
    }

    function show(trigger, meta) {
        if (current === trigger) { clearTimeout(hideTimer); return; }
        card.innerHTML = cardHtml(meta);
        card.hidden = false;
        current = trigger;
        trigger.setAttribute("aria-describedby", "inspect-card");
        if (cleanup) { cleanup(); }
        cleanup = FUI.autoUpdate(trigger, card, function () { place(trigger); });
    }

    function hide() {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        if (!current) { return; }
        card.hidden = true;
        card.innerHTML = "";
        current.removeAttribute("aria-describedby");
        current = null;
        if (cleanup) { cleanup(); cleanup = null; }
    }

    function scheduleShow(hit) {
        clearTimeout(hideTimer);
        if (current === hit.trigger) { return; }
        clearTimeout(showTimer);
        showTimer = setTimeout(function () { show(hit.trigger, hit.meta); }, 250);
    }

    function scheduleHide() {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hide, 150);
    }

    // --- hover (mouse) ---
    grid.addEventListener("mouseover", function (e) {
        var hit = metaFor(e.target);
        if (hit) { scheduleShow(hit); }
    });
    grid.addEventListener("mouseout", function (e) {
        var t = e.target.closest ? e.target.closest("[data-path]") : null;
        if (!t) { return; }
        if (e.relatedTarget && t.contains(e.relatedTarget)) { return; }
        scheduleHide();
    });
    card.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    card.addEventListener("mouseleave", scheduleHide);

    // --- keyboard focus ---
    grid.addEventListener("focusin", function (e) {
        var hit = metaFor(e.target);
        if (hit) { show(hit.trigger, hit.meta); }
    });
    grid.addEventListener("focusout", function (e) {
        if (e.relatedTarget && card.contains(e.relatedTarget)) { return; }
        scheduleHide();
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { hide(); }
    });

    // --- touch: first tap opens the card, a second tap follows the link ---
    document.addEventListener("pointerdown", function (e) {
        lastPointerType = e.pointerType || "mouse";
        if (current && !current.contains(e.target) && !card.contains(e.target)) {
            hide();
        }
    }, true);
    grid.addEventListener("click", function (e) {
        if (lastPointerType !== "touch") { return; }
        var hit = metaFor(e.target);
        if (!hit || current === hit.trigger) { return; }
        e.preventDefault();
        show(hit.trigger, hit.meta);
    }, true);

    // Mark the nodes that actually have a card so CSS can hint them (the help
    // cursor); re-run after each polled grid swap, and drop a card whose trigger
    // was just replaced.
    function markTriggers() {
        var nodes = grid.querySelectorAll("[data-path]");
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].classList.toggle("inspect-trigger",
                Object.prototype.hasOwnProperty.call(
                    META, nodes[i].getAttribute("data-path")));
        }
    }
    markTriggers();
    new MutationObserver(function () {
        markTriggers();
        if (current && !grid.contains(current)) { hide(); }
    }).observe(grid, { childList: true, subtree: true });
})();
