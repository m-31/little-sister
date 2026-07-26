/* Branch density (ADR-0024) — the "+N more" reveal for a level's capped boxes.
 *
 * In the dense view a branch caps the quiet (non-warn/error) child boxes it shows to
 * config.yaml ``branch_cap``; the surplus are server-marked ``.is-extra`` (hidden by
 * CSS) and the level carries a ``.branch-more`` button. Clicking it toggles the
 * container's ``.is-expanded`` class in place — CSS then shows the boxes and swaps the
 * button label. No measurement is needed: the cap is an exact server-side count,
 * unlike the reason chevron, which must measure line overflow in the browser.
 *
 * Bound once via event delegation on #status-grid, so it survives the ~10s grid
 * innerHTML swaps (the inspection-popover pattern, ADR-0019). A page-lifetime set of
 * expanded branch paths is re-applied after every swap; there is no storage, so a
 * reload resets — right for a glance surface.
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    if (!grid) { return; }

    // Branch path -> true for every container the viewer has expanded (page lifetime).
    var expanded = Object.create(null);
    var observer = null;

    // The reveal button is the container's own direct child. A nested container's
    // button sorts earlier in the DOM, so a plain querySelector would find the wrong
    // one — scan the immediate children instead.
    function moreButton(container) {
        var kids = container.children;
        for (var i = 0; i < kids.length; i++) {
            if (kids[i].classList && kids[i].classList.contains("branch-more")) {
                return kids[i];
            }
        }
        return null;
    }

    function apply(container) {
        var open = !!expanded[container.getAttribute("data-branch")];
        container.classList.toggle("is-expanded", open);
        var btn = moreButton(container);
        if (btn) { btn.setAttribute("aria-expanded", open ? "true" : "false"); }
    }

    function syncAll() {
        // Detach while we mutate, so our own edits don't re-trigger the observer;
        // reattach when done (the reasons.js pattern).
        if (observer) { observer.disconnect(); }
        var containers = grid.querySelectorAll(".node-children[data-branch]");
        for (var i = 0; i < containers.length; i++) { apply(containers[i]); }
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    grid.addEventListener("click", function (e) {
        var btn = e.target.closest ? e.target.closest(".branch-more") : null;
        if (!btn) { return; }
        // A control, not navigation — keep the click off the card link and the
        // popover's touch handler.
        e.preventDefault();
        e.stopPropagation();
        var container = btn.closest(".node-children");
        if (!container) { return; }
        var branch = container.getAttribute("data-branch");
        if (expanded[branch]) { delete expanded[branch]; } else { expanded[branch] = true; }
        apply(container);
    });

    observer = new MutationObserver(syncAll);
    syncAll();
})();
