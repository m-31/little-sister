/* Stable-flow dashboard card spans (ADR-0056).
 *
 * The server owns product semantics: each card carries stable flow diagnostics
 * and the grid carries width breakpoints — `[tenths, tracks, plan]` bands, the
 * smallest grid width in **tenths of a pixel** at which each deterministic plan
 * applies.  Tenths are the model's own unit and a browser reports a fractional
 * width, so the comparison below scales the measurement rather than rounding the
 * threshold: rounding up to whole pixels used to leave a band up to 0.9px late,
 * and a wall could carry a plan far worse than an available one across that gap.
 * The browser owns the one fact only it knows: how wide the responsive grid
 * currently is.  A band names the outer track count its plan was priced for,
 * and this script sets the grid to exactly that many equal tracks — that is
 * what stops CSS auto-fill from snapping every track back to the 330px minimum
 * the moment one more fits, which used to make a one-pixel-wider viewport paint
 * a dramatically taller page.  A track count of 0 means "let auto-fill decide"
 * (only ever sent with an all-ones plan, which is valid at any count).
 * Selecting a band never inspects card height, status, live reasons or chip/box
 * painting, so a status-only poll cannot move a root.
 *
 * The persistent #status-grid container is observed rather than the replaceable
 * .status-grid element.  That makes one binding cover the initial page, the ~10s
 * poll's innerHTML swap, viewport changes and rail expansion.  If data is absent
 * or malformed, inline spans and columns are cleared and CSS's ordinary
 * auto-fill grid wins.
 */
(function () {
    "use strict";

    var root = document.getElementById("status-grid");
    if (!root) { return; }

    var queued = false;
    var observedWidth = null;

    function cardsOf(grid) {
        var cards = [];
        for (var i = 0; i < grid.children.length; i++) {
            if (grid.children[i].classList.contains("status-card")) {
                cards.push(grid.children[i]);
            }
        }
        return cards;
    }

    function clear(grid, cards) {
        grid.style.gridTemplateColumns = "";
        grid.removeAttribute("data-layout-tracks");
        for (var i = 0; i < cards.length; i++) {
            cards[i].style.gridColumn = "";
            cards[i].removeAttribute("data-layout-span");
        }
    }

    function trackCount(grid) {
        // Inline columns have already been cleared, so the computed explicit
        // grid is CSS's auto-fill fallback. Browsers resolve repeat()/minmax()
        // to one whitespace-separated used value per track. Used only as the
        // safety clamp when a band leaves the count to auto-fill — selection
        // and explicit counts go by measured width.
        var columns = getComputedStyle(grid).gridTemplateColumns.trim();
        if (!columns || columns === "none") { return 1; }
        return columns.split(/\s+/).length;
    }

    function layout() {
        queued = false;
        var grid = root.querySelector(".status-grid");
        if (!grid) { return; }
        var cards = cardsOf(grid);
        clear(grid, cards);
        if (!cards.length) { return; }

        var breakpoints;
        try {
            breakpoints = JSON.parse(
                grid.getAttribute("data-layout-breakpoints") || ""
            );
        } catch (error) {
            return;
        }
        if (!Array.isArray(breakpoints) || !breakpoints.length) { return; }

        var width = grid.getBoundingClientRect().width * 10;
        var tracks = 0;
        var plan = null;
        var previousWidth = 0;
        for (var point = 0; point < breakpoints.length; point++) {
            var entry = breakpoints[point];
            if (!Array.isArray(entry) || entry.length !== 3) { return; }
            var entryWidth = Number(entry[0]);
            var entryTracks = Number(entry[1]);
            if (!Number.isInteger(entryWidth) || entryWidth < 1
                    || (point > 0 && entryWidth <= previousWidth)
                    || !Number.isInteger(entryTracks) || entryTracks < 0) {
                return;
            }
            previousWidth = entryWidth;
            if (entryWidth > width) { break; }
            tracks = entryTracks;
            plan = entry[2];
        }
        if (!Array.isArray(plan) || plan.length !== cards.length) { return; }
        if (tracks > 0) {
            grid.style.gridTemplateColumns =
                "repeat(" + tracks + ", minmax(0, 1fr))";
            grid.setAttribute("data-layout-tracks", String(tracks));
        } else {
            tracks = Math.max(1, trackCount(grid));
        }
        for (var i = 0; i < cards.length; i++) {
            var span = Number(plan[i]);
            if (!Number.isInteger(span) || span < 1 || span > tracks) {
                clear(grid, cards);
                return;
            }
            cards[i].style.gridColumn = "span " + span;
            cards[i].setAttribute("data-layout-span", String(span));
        }
    }

    function schedule() {
        if (queued) { return; }
        queued = true;
        window.requestAnimationFrame(layout);
    }

    new MutationObserver(schedule).observe(root, {childList: true, subtree: true});
    new ResizeObserver(function (entries) {
        var width = entries.length ? entries[0].contentRect.width : root.clientWidth;
        if (width !== observedWidth) {
            observedWidth = width;
            schedule();
        }
    }).observe(root);
    schedule();
}());
