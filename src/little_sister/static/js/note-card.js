/* A block's note, opened from its mark on the wall (ADR-0135 decision 3).
 *
 * On the wall a rule's block says its mark and its sentence, and its note waits
 * behind a mark of its own — a link to the page that states the block whole. Here a
 * plain click, a tap, Enter or Space on that mark opens the note instead, in a card
 * in the inspection card's look and place (ADR-0019): above the block, placed by
 * Floating UI, with the node's name, the block's sentence, the note whole from the
 * block's own <template class="rule-note-src">, who set it and when, and a link to
 * the node's page. A modified or middle click keeps the link's meaning.
 *
 * Where the viewer's look opens cards on a pause (`inspection_card`, ADR-0029), a
 * pause on the mark opens the card too, and leaving the mark and the card closes
 * what a pause opened; a click keeps it open. Escape, a click elsewhere or the mark
 * again closes it, Escape handing the focus back to the mark where the card had it.
 *
 * Bound once by event delegation on #status-grid, so it survives the ~10s swaps of
 * the grid; after one — `poll.js`'s `ls:swapped`, so that no fourth script watches
 * the grid — the card stays on its block, found again by the pin's key and the node
 * the block stands in, its note read anew, and closes only where that block is gone.
 * The card stands outside the grid the refresh swaps.
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    var card = document.getElementById("note-card");
    if (!grid || !card || !window.FloatingUIDOM) { return; }
    var FUI = window.FloatingUIDOM;

    var MARK = ".rule-note-mark";
    // How long the pointer rests on a mark before a pause opens its card, and how
    // long it may be away from both the mark and the card before that card closes.
    var REST_MS = 650;
    var LEAVE_MS = 300;
    var pauses = document.body.getAttribute("data-ls-inspection-card") !== "off";

    var current = null;      // the mark the card is open for
    var currentKey = "";
    var openedBy = "";       // "click" or "pause"
    var cleanup = null;      // Floating UI autoUpdate teardown
    var restTimer = null;
    var leaveTimer = null;

    // The node a block stands in: a box's tree node, or a card, whose head row
    // carries its path.
    function standing(mark) {
        var node = mark.closest("[data-node]");
        if (node) { return node.getAttribute("data-node") || ""; }
        var box = mark.closest(".status-card");
        var head = box ? box.querySelector("[data-path]") : null;
        return head ? (head.getAttribute("data-path") || "") : "";
    }

    function keyOf(mark) {
        return standing(mark) + "#" + (mark.getAttribute("data-note-key") || "");
    }

    function blockOf(mark) {
        return mark.closest(".rule-block");
    }

    function nameOf(mark) {
        var box = mark.closest(".status-node, .status-card");
        var name = box ? box.querySelector(".status-node__name, .status-card__name") : null;
        return name ? (name.textContent || "").trim() : "";
    }

    function fill(mark) {
        var block = blockOf(mark);
        var source = block ? block.querySelector("template.rule-note-src") : null;
        if (!source) { return false; }
        card.textContent = "";
        var name = nameOf(mark);
        var heading = document.createElement("div");
        heading.className = "inspect-card__title";
        heading.textContent = name;
        card.appendChild(heading);
        var what = block.querySelector(".rule-block__what");
        if (what) {
            var sentence = document.createElement("div");
            sentence.className = "note-card__sentence";
            sentence.innerHTML = what.innerHTML;   // the server's own markup
            card.appendChild(sentence);
        }
        card.appendChild(source.content.cloneNode(true));
        var page = document.createElement("a");
        page.className = "inspect-card__more";
        page.href = mark.getAttribute("href") || "";
        page.textContent = (name ? name + "’s page" : "The node’s page") + " ↗";
        card.appendChild(page);
        return true;
    }

    function place() {
        if (!current) { return; }
        var reference = blockOf(current) || current;
        FUI.computePosition(reference, card, {
            strategy: "fixed",
            placement: "top",
            middleware: [FUI.offset(8), FUI.flip(), FUI.shift({ padding: 8 })]
        }).then(function (position) {
            card.style.left = position.x + "px";
            card.style.top = position.y + "px";
        });
    }

    function anchor(mark) {
        if (cleanup) { cleanup(); }
        cleanup = FUI.autoUpdate(blockOf(mark) || mark, card, place);
    }

    function open(mark, by, focus) {
        clearTimeout(restTimer);
        clearTimeout(leaveTimer);
        if (current && current !== mark) { current.setAttribute("aria-expanded", "false"); }
        if (!fill(mark)) { return; }
        current = mark;
        currentKey = keyOf(mark);
        openedBy = by;
        card.hidden = false;
        mark.setAttribute("aria-expanded", "true");
        anchor(mark);
        if (focus) { card.focus({ preventScroll: true }); }
    }

    function close(returnFocus) {
        clearTimeout(restTimer);
        clearTimeout(leaveTimer);
        if (!current) { return; }
        var mark = current;
        var hadFocus = card.contains(document.activeElement);
        card.hidden = true;
        card.textContent = "";
        current = null;
        currentKey = "";
        openedBy = "";
        if (cleanup) { cleanup(); cleanup = null; }
        if (grid.contains(mark)) {
            mark.setAttribute("aria-expanded", "false");
            if (returnFocus && hadFocus) { mark.focus({ preventScroll: true }); }
        }
    }

    // A plain click, a tap, or Enter — which a link turns into a click — opens or
    // closes the card; a click that opened by a pause keeps it open.
    grid.addEventListener("click", function (event) {
        var mark = event.target.closest ? event.target.closest(MARK) : null;
        if (!mark || !grid.contains(mark)) { return; }
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey
                || event.altKey) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        if (current === mark && openedBy === "click") { close(true); return; }
        // A click from the keyboard carries no pointer (`detail` 0): the card takes
        // the focus, so that what it says is read, and Escape hands it back.
        open(mark, "click", event.detail === 0);
    });

    // Space is a button's key, and the mark is one here.
    grid.addEventListener("keydown", function (event) {
        if (event.key !== " ") { return; }
        var mark = event.target.closest ? event.target.closest(MARK) : null;
        if (!mark) { return; }
        event.preventDefault();
        if (current === mark && openedBy === "click") { close(true); return; }
        open(mark, "click", true);
    });

    document.addEventListener("click", function (event) {
        if (!current) { return; }
        if (card.contains(event.target)) { return; }
        if (event.target.closest && event.target.closest(MARK)) { return; }
        close(false);
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && current) { close(true); }
    });

    if (pauses) {
        grid.addEventListener("pointerover", function (event) {
            if (event.pointerType && event.pointerType !== "mouse") { return; }
            var mark = event.target.closest ? event.target.closest(MARK) : null;
            if (!mark) { return; }
            clearTimeout(leaveTimer);
            if (current === mark) { return; }
            clearTimeout(restTimer);
            restTimer = setTimeout(function () {
                if (!current || openedBy === "pause") { open(mark, "pause", false); }
            }, REST_MS);
        });
        grid.addEventListener("pointerout", function (event) {
            var mark = event.target.closest ? event.target.closest(MARK) : null;
            if (!mark) { return; }
            if (event.relatedTarget && mark.contains(event.relatedTarget)) { return; }
            clearTimeout(restTimer);
            if (current && openedBy === "pause") {
                leaveTimer = setTimeout(function () { close(false); }, LEAVE_MS);
            }
        });
        card.addEventListener("pointerenter", function () { clearTimeout(leaveTimer); });
        card.addEventListener("pointerleave", function () {
            if (current && openedBy === "pause") {
                leaveTimer = setTimeout(function () { close(false); }, LEAVE_MS);
            }
        });
    }

    // The refresh replaces the grid's contents: the card stays on its block, found
    // again by its key, its note read anew; it closes where the block is gone.
    document.addEventListener("ls:swapped", function () {
        if (!current || grid.contains(current)) { return; }
        var found = null;
        var marks = grid.querySelectorAll(MARK);
        for (var i = 0; i < marks.length; i++) {
            if (keyOf(marks[i]) === currentKey) { found = marks[i]; break; }
        }
        if (!found) { close(false); return; }
        var by = openedBy;
        var focused = card.contains(document.activeElement);
        current = found;
        if (!fill(found)) { close(false); return; }
        openedBy = by;
        found.setAttribute("aria-expanded", "true");
        anchor(found);
        if (focused) { card.focus({ preventScroll: true }); }
    });
})();
