/* Reason overflow (#9).
 *
 * A dashboard card caps how many reason entries it shows and clamps a tall
 * reason block's height; a per-node "show all (N)" toggles both, expanding in
 * place with no round trip. Every entry is already in the DOM (the server hides
 * the remainder with CSS — never a mid-HTML cut, ADR-0018), so expanding is pure
 * class toggling.
 *
 * Bound once via event delegation on #status-grid, so it survives the ~10s grid
 * innerHTML swaps (the inspection-popover pattern, ADR-0019). A page-lifetime Set
 * of expanded node paths is re-applied after every swap; there is no storage, so
 * a reload resets — right for a glance surface. The leaf detail page always shows
 * everything; the JSON envelope is untouched.
 *
 * Two overflow shapes, one toggle: the entry cap is known server-side (it renders
 * the toggle and marks the extra entries), while a single tall entry that fits
 * under the cap is only measurable here — so this script adds the toggle for the
 * height case and marks the block .is-clipped for the fade.
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    if (!grid) { return; }

    // Overflow beyond the clamp smaller than this (px) isn't worth a toggle —
    // keeps a block that spills by a rounding sliver from sprouting one.
    var CLIP_SLOP = 8;
    // Node path -> true for every block the viewer has expanded (page lifetime).
    var expanded = Object.create(null);
    var observer = null;

    function toggleAfter(block) {
        var t = block.nextElementSibling;
        return t && t.classList.contains("reason-toggle") ? t : null;
    }

    function blockBefore(toggle) {
        var b = toggle.previousElementSibling;
        return b && b.classList.contains("reason-block") ? b : null;
    }

    function apply(block) {
        var path = block.getAttribute("data-reason-node");
        var open = !!expanded[path];
        block.classList.toggle("is-open", open);

        // Measure only while collapsed: hidden .reason-extra entries don't add to
        // scrollHeight, so this catches a tall *visible* block (a code() trace)
        // even when the entry count is under the cap. An open block keeps its
        // toggle so it can be collapsed again.
        var clipped = !open &&
            block.scrollHeight - block.clientHeight > CLIP_SLOP;
        block.classList.toggle("is-clipped", clipped);

        var hasExtra = block.querySelector(".reason-extra") !== null;
        var toggle = toggleAfter(block);
        if ((hasExtra || clipped || open) && !toggle) {
            toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "reason-toggle";
            toggle.setAttribute("data-reason-toggle", "");
            block.insertAdjacentElement("afterend", toggle);
        }
        if (toggle) {
            var total = block.getAttribute("data-reason-total") || "";
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
            toggle.textContent = open ? "show less" : "show all (" + total + ")";
        }
    }

    function syncAll() {
        // Detach while we mutate (injecting toggles is a DOM change), so our own
        // edits don't re-trigger the observer; reattach when done.
        if (observer) { observer.disconnect(); }
        var blocks = grid.querySelectorAll(".reason-block");
        for (var i = 0; i < blocks.length; i++) { apply(blocks[i]); }
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    grid.addEventListener("click", function (e) {
        var toggle = e.target.closest ? e.target.closest(".reason-toggle") : null;
        if (!toggle) { return; }
        // The toggle is a control, not navigation — don't let the click reach the
        // card link or the popover's touch handler.
        e.preventDefault();
        e.stopPropagation();
        var block = blockBefore(toggle);
        if (!block) { return; }
        var path = block.getAttribute("data-reason-node");
        if (expanded[path]) { delete expanded[path]; } else { expanded[path] = true; }
        apply(block);
    });

    observer = new MutationObserver(syncAll);
    syncAll();
})();
