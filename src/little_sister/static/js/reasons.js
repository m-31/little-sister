/* Reason overflow (ADR-0024) — the show-all / collapse control.
 *
 * A card clamps its reasons to a line budget (the block's ``--reason-lines``, from
 * config.yaml ``reason_cap``); the overflow stays in the DOM, clipped by CSS and
 * faded (ADR-0018). A single chevron in the card header, just after the status
 * word, toggles it: ▼ when the reasons overflow the budget (click to show all), ▲
 * when expanded (click to collapse), and an empty same-width slot otherwise so the
 * status words stay aligned. Nested nodes, which have no status word, get the
 * chevron pinned to the top-right of their name row instead.
 *
 * Bound once via event delegation on #status-grid, so it survives the ~10s grid
 * innerHTML swaps (the inspection-popover pattern, ADR-0019). A page-lifetime Set
 * of expanded node paths is re-applied after every swap; there is no storage, so a
 * reload resets — right for a glance surface. Whether a block overflows its budget
 * is only measurable here, so the chevron is entirely client-side; the leaf detail
 * page always shows everything, and the JSON envelope is untouched.
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    if (!grid) { return; }

    // Overflow beyond the budget smaller than this (px) isn't worth a chevron —
    // keeps a block that spills by a rounding sliver from sprouting one.
    var CLIP_SLOP = 8;
    // Node path -> true for every block the viewer has expanded (page lifetime).
    var expanded = Object.create(null);
    var observer = null;

    // The chevron lives in the header: a card's block uses the server-rendered slot
    // after the status word, and a nested node's block finds the same slot in its
    // state cluster; creating a pinned one is the fallback for a row without it.
    function chevronFor(block) {
        var nodeSelf = block.closest(".status-node__self");
        if (nodeSelf) {
            var nc = nodeSelf.querySelector(".reason-chevron");
            if (!nc) {
                nc = document.createElement("button");
                nc.type = "button";
                nc.className = "reason-chevron reason-chevron--node";
                nodeSelf.insertBefore(nc, nodeSelf.firstChild);
            }
            return nc;
        }
        var card = block.closest(".status-card");
        return card ? card.querySelector(".status-card__head .reason-chevron") : null;
    }

    // The block a chevron controls: a card's own reason block (a direct child of the
    // panel) or the node's own block inside its self row.
    function blockFor(chevron) {
        var nodeSelf = chevron.closest(".status-node__self");
        if (nodeSelf) { return nodeSelf.querySelector(".reason-block"); }
        var card = chevron.closest(".status-card");
        return card ? card.querySelector(".status-panel > .reason-block") : null;
    }

    function apply(block) {
        var path = block.getAttribute("data-reason-node");
        var open = !!expanded[path];
        block.classList.toggle("is-open", open);

        // Whether the reasons overflow the line budget is only measurable here (the
        // clamp is CSS). Measure while collapsed; an open block keeps its chevron so
        // it can be folded again.
        var clipped = !open && block.scrollHeight - block.clientHeight > CLIP_SLOP;
        block.classList.toggle("is-clipped", clipped);

        var chevron = chevronFor(block);
        if (!chevron) { return; }
        if (open || clipped) {
            var total = block.getAttribute("data-reason-total") || "";
            chevron.classList.add("is-active");
            chevron.textContent = open ? "▲" : "▼";        // ▲ / ▼
            chevron.tabIndex = 0;
            chevron.removeAttribute("aria-hidden");
            chevron.setAttribute("aria-expanded", open ? "true" : "false");
            chevron.setAttribute(
                "aria-label", open ? "collapse reasons" : "show all " + total + " reasons");
            chevron.setAttribute("title", open ? "collapse" : "show all (" + total + ")");
        } else {
            // Nothing to toggle: a card slot goes empty (its width is reserved, so the
            // status words stay aligned); a node chevron with no job is removed.
            chevron.classList.remove("is-active");
            chevron.textContent = "";
            chevron.tabIndex = -1;
            chevron.setAttribute("aria-hidden", "true");
            chevron.removeAttribute("aria-expanded");
            chevron.removeAttribute("aria-label");
            chevron.removeAttribute("title");
            if (chevron.classList.contains("reason-chevron--node")) { chevron.remove(); }
        }
    }

    function syncAll() {
        // Detach while we mutate (injecting/updating chevrons is a DOM change), so our
        // own edits don't re-trigger the observer; reattach when done.
        if (observer) { observer.disconnect(); }
        var blocks = grid.querySelectorAll(".reason-block");
        for (var i = 0; i < blocks.length; i++) { apply(blocks[i]); }
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    grid.addEventListener("click", function (e) {
        var chevron = e.target.closest
            ? e.target.closest(".reason-chevron.is-active") : null;
        if (!chevron) { return; }
        // A control, not navigation — keep the click off the card link and the
        // popover's touch handler.
        e.preventDefault();
        e.stopPropagation();
        var block = blockFor(chevron);
        if (!block) { return; }
        var path = block.getAttribute("data-reason-node");
        if (expanded[path]) { delete expanded[path]; } else { expanded[path] = true; }
        apply(block);
    });

    observer = new MutationObserver(syncAll);
    syncAll();
})();
