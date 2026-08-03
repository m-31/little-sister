/* The card pin control (backlog #35; ADR-0014 data).
 *
 * An admin's pin control in a card head — an <a> to the node's own page, so
 * no JavaScript (or no Floating UI) still lands on a page carrying the
 * maintenance card — upgraded here to open the #pin-card dialog beside the
 * card: ONE body-level form shared by every card, so the ~10s poll fragment
 * carries only a small control per card and an open form is never swapped out
 * from under the admin. The maintenance.js conventions throughout: event
 * delegation on #status-grid, Floating UI positioning, Escape / outside click
 * close, a MutationObserver that re-anchors the dialog across the poll's swap and
 * drops it only when the node itself is gone. Being a form rather than a list, it
 * also manages focus: the reason field on open, back to the trigger on an explicit
 * close.
 *
 * A pinned card gets the SAME form, prefilled (ADR-0014 amendment) — who pinned
 * it and until when, its stored reason in the field, "Save changes" on the
 * button and "Clear maintenance" beneath. Both forms also carry the control's
 * `data-pin-token` (the entry's `set_at`) as the compare-and-set token; an
 * unpinned card sends it empty, which says "I believe nothing is pinned".
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    var card = document.getElementById("pin-card");
    if (!grid || !card || !window.FloatingUIDOM) { return; }
    var FUI = window.FloatingUIDOM;

    var nameEl = document.getElementById("pin-card-name");
    var pathEl = document.getElementById("pin-card-path");
    var setEl = document.getElementById("pin-card-set");
    var clearEl = document.getElementById("pin-card-clear");
    var setInput = document.getElementById("pin-card-input");
    var clearInput = document.getElementById("pin-card-clear-input");
    var setToken = document.getElementById("pin-card-token");
    var clearToken = document.getElementById("pin-card-clear-token");
    var pinnedEl = document.getElementById("pin-card-pinned");
    var byEl = document.getElementById("pin-card-by");
    var expiresEl = document.getElementById("pin-card-expires");
    var reasonEl = document.getElementById("pin-reason");
    var durationEl = document.getElementById("pin-duration");
    var durationLabel = document.getElementById("pin-duration-label");
    var submitEl = document.getElementById("pin-card-submit");

    var current = null;   // the control the dialog is currently open for
    var cleanup = null;   // Floating UI autoUpdate teardown

    function place(trigger) {
        FUI.computePosition(trigger, card, {
            strategy: "fixed",
            placement: "bottom-end",
            middleware: [FUI.offset(6), FUI.flip(), FUI.shift({ padding: 8 })]
        }).then(function (pos) {
            card.style.left = pos.x + "px";
            card.style.top = pos.y + "px";
        });
    }

    function open(trigger) {
        var path = trigger.getAttribute("data-pin-path");
        var pinned = trigger.hasAttribute("data-pin-pinned");
        nameEl.textContent = trigger.getAttribute("data-pin-name") || path;
        pathEl.textContent = path;
        card.setAttribute("aria-label", "maintenance for " + path);
        var token = trigger.getAttribute("data-pin-token") || "";
        setInput.value = path;
        clearInput.value = path;
        // Both writes name the pin they believe they are replacing; an unpinned
        // card sends "", which is the claim that nothing is pinned.
        setToken.value = token;
        clearToken.value = token;
        setEl.hidden = false;
        clearEl.hidden = !pinned;
        // Pinned: the same form, prefilled and relabeled as an edit, so
        // extending a window never means clearing first.
        pinnedEl.hidden = !pinned;
        reasonEl.value = pinned ? (trigger.getAttribute("data-pin-reason") || "") : "";
        // Reset the duration too. One dialog serves every card, so a value left
        // over from the card before it would silently re-time this one — and on an
        // edit, silently re-time a window the admin only meant to re-word.
        durationEl.value = "";
        durationLabel.textContent = pinned ? "New window, from now" : "Duration";
        submitEl.textContent = pinned ? "Save changes" : "Set maintenance";
        if (pinned) {
            var by = trigger.getAttribute("data-pin-by");
            var expires = trigger.getAttribute("data-pin-expires");
            // "set by", not "pinned by": in a compact place the honest name is
            // the one whose words the reason field is showing — the last writer.
            byEl.textContent = by ? ", set by " + by : "";
            expiresEl.textContent = expires ? " — expires " + expires : "";
        }
        // the promise sentence matches what the pin covers: subtree or leaf, and
        // is only a promise while the pin is still to be made
        var kids = trigger.hasAttribute("data-pin-kids");
        card.querySelectorAll(".pin-card__promise").forEach(function (p) {
            p.hidden = pinned || (p.getAttribute("data-variant") === "branch") !== kids;
        });
        card.hidden = false;
        current = trigger;
        trigger.setAttribute("aria-expanded", "true");
        if (cleanup) { cleanup(); }
        cleanup = FUI.autoUpdate(trigger, card, function () { place(trigger); });
        reasonEl.focus();
    }

    function close(refocus) {
        if (!current) { return; }
        card.hidden = true;
        current.setAttribute("aria-expanded", "false");
        if (refocus && document.contains(current)) { current.focus(); }
        current = null;
        if (cleanup) { cleanup(); cleanup = null; }
    }

    // A control click toggles the dialog. The control is a link to the node's
    // page; a modified click (new tab/window) is left to the browser, like the
    // maintenance pill.
    grid.addEventListener("click", function (e) {
        var trigger = e.target.closest ? e.target.closest(".pin-control") : null;
        if (!trigger) { return; }
        if (e.metaKey || e.ctrlKey || e.shiftKey) { return; }
        e.preventDefault();
        e.stopPropagation();
        if (current === trigger) { close(true); return; }
        close(false);
        open(trigger);
    });

    // Click anywhere outside the open dialog closes it; a click inside (the
    // form) is left alone.
    document.addEventListener("click", function (e) {
        if (!current) { return; }
        if (card.contains(e.target) || current.contains(e.target)) { return; }
        close(false);
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { close(true); }
    });

    // The ~10s poll replaces #status-grid's contents wholesale, so the open
    // dialog's anchor is detached on *every* poll — not only when the control
    // genuinely went away. Closing on that emptied the form the admin was typing
    // into roughly every ten seconds, which is precisely what putting the dialog
    // outside the grid was supposed to prevent.
    //
    // So re-anchor instead: find the replacement control for the same node and
    // adopt it. The form is deliberately left alone — its fields are the admin's
    // work in progress, and its `set_at` token is the pin it believes it is
    // replacing. Refreshing that token from the new markup would quietly re-aim
    // the write at whatever landed in the meantime, which is the compare-and-set
    // guard defeating itself. If no replacement exists the node really is gone,
    // and only then does the dialog close.
    new MutationObserver(function () {
        if (!current || grid.contains(current)) { return; }
        var path = current.getAttribute("data-pin-path");
        var replacement = path && grid.querySelector(
            '.pin-control[data-pin-path="' + (window.CSS && CSS.escape
                ? CSS.escape(path) : path) + '"]');
        if (!replacement) { close(false); return; }
        current.setAttribute("aria-expanded", "false");
        current = replacement;
        current.setAttribute("aria-expanded", "true");
        if (cleanup) { cleanup(); }
        cleanup = FUI.autoUpdate(current, card, function () { place(current); });
    }).observe(grid, { childList: true, subtree: true });
})();
