/* Inspection popover (ADR-0019, ADR-0127 decision 11).
 *
 * A hover card for a node: its name and title as the node's own head draws them —
 * every node's box carries its head, open or closed — and the first block of its
 * `about` with how many blocks follow, which the grid's fragment carries in
 * #node-meta (`_status_grid.html`) and which is read again after every swap, so a
 * node a run names after the load has its card and a changed `about` is current.
 * A node with neither a title nor an `about` has no card, and the card keeps the
 * node's state out: the chip or the head under the pointer shows it. Bound once by
 * event delegation on #status-grid, so it survives the ~10s grid swaps, and placed
 * with Floating UI.
 *
 * It opens on a node's **name** alone — a chip, the name in an open node's head
 * (`[data-control="toggle"]`), the status strip's name — once the pointer has
 * rested there about two thirds of a second, so a pointer on its way to a click
 * opens nothing; never over a head's icons, a box's lines or a line's actions, nor
 * while a click is under way or just after one. Focus on a name from the keyboard
 * opens it at once. It stays open while the pointer moves into it, and closes when
 * the pointer leaves the name for anywhere but the card, on blur and with Escape.
 * On touch a tap opens or closes the node (tree.js) and the card is not offered.
 * Under the look `inspection_card: off` (`looks.py`, an attribute on <body>) it
 * never opens, for the pointer and the keyboard alike.
 */
(function () {
    "use strict";

    var grid = document.getElementById("status-grid");
    var card = document.getElementById("inspect-card");
    if (!grid || !card || !window.FloatingUIDOM) { return; }
    if (document.body.getAttribute("data-ls-inspection-card") === "off") { return; }
    var FUI = window.FloatingUIDOM;

    // A node's name, which is what the card answers to: a chip, the toggle in an
    // open node's head, and the status strip's name. A node's page's own head has
    // no toggle — its `about` is open in the band above it — and no card.
    var NAMES = '.tree-chip, [data-control="toggle"], .ls-strip__name';
    // Where a node's head draws its name and its title.
    var HEAD_NAME = ".status-card__name, .status-node__name, .ls-strip__name";
    // How long the pointer rests on a name before its card opens, and how long after
    // a click none does: the pointer that clicked is left on the name it toggled.
    var REST_MS = 650;
    var AFTER_CLICK_MS = 600;

    // A pin's editor, open: the shape the refresh waits for (poll.js, ADR-0104
    // decision 7) — the editor's own disclosure, so no other matches it. A node
    // whose pin is being written says nothing else about itself: the control that
    // opened the editor has given way to it, the pointer that clicked is left on the
    // node's own row, and its card would come up over the one above and stand there
    // while the note is typed. The editor stands in the node's box, after its row
    // (ADR-0127 decision 3), so the node is what is asked.
    var EDITOR = "details.maintenance-editor-disclosure[open] form.maintenance-editor-form, details.reason-pin[open] form.maintenance-editor-form";

    // What each node's `about` opens with, as the fragment the grid holds says it.
    var META = {};
    var metaElement = null;
    function readMeta() {
        var element = document.getElementById("node-meta");
        if (element === metaElement) { return; }
        metaElement = element;
        META = {};
        if (!element) { return; }
        try { META = JSON.parse(element.textContent || "{}") || {}; } catch (e) { META = {}; }
    }

    var current = null;            // the name the card is shown for
    var currentPath = "", currentKind = "";
    var cleanup = null;            // Floating UI autoUpdate teardown
    var showTimer = null, hideTimer = null;
    var resting = null;            // the name the pointer is on
    var pressed = false;           // a click under way in the grid
    var quietUntil = 0;            // and the moment after one

    function nameOf(element) {
        var name = element && element.closest ? element.closest(NAMES) : null;
        return name && grid.contains(name) ? name : null;
    }

    function kindOf(name) {
        if (name.classList.contains("tree-chip")) { return "chip"; }
        return name.classList.contains("ls-strip__name") ? "strip" : "head";
    }

    function rowOf(name) {
        return name.hasAttribute("data-path") ? name : name.closest("[data-path]");
    }

    function selectorFor(path) {
        return '[data-path="' + path.replace(/["\\]/g, "\\$&") + '"]';
    }

    // The node's own head row, where its name and title are drawn: for a chip, the
    // head in its box, which stands beside the chip in the node, hidden while the
    // node is closed.
    function headOf(row) {
        if (!row.classList.contains("tree-chip")) { return row; }
        var node = row.closest(".tree-node");
        return node ? node.querySelector(selectorFor(row.getAttribute("data-path"))
                                         + ":not(.tree-chip)") : null;
    }

    function cardOf(name) {
        var row = name ? rowOf(name) : null;
        if (!row) { return null; }
        var node = row.closest(".tree-node") || row;
        if (node.querySelector(EDITOR)) { return null; }
        var path = row.getAttribute("data-path");
        var head = headOf(row);
        var title = head ? head.querySelector(".node-title") : null;
        var meta = Object.prototype.hasOwnProperty.call(META, path) ? META[path] : null;
        if (!title && !meta) { return null; }
        return { name: name, path: path, head: head, title: title, meta: meta };
    }

    // The card, from the node's head and its `about`'s first block: its name, the
    // title beside it as the head draws it, then the block, and where the `about`
    // has more, a line to the node's page that counts it.
    function fill(hit) {
        card.textContent = "";
        var heading = document.createElement("div");
        heading.className = "inspect-card__title";
        var label = hit.head ? hit.head.querySelector(HEAD_NAME) : null;
        heading.appendChild(document.createTextNode(
            ((label || hit.name).textContent || "").trim()));
        if (hit.title) {
            var title = document.createElement("span");
            title.className = "inspect-card__node-title";
            title.innerHTML = hit.title.innerHTML;     // the head's own markup
            heading.appendChild(document.createTextNode(" "));
            heading.appendChild(title);
        }
        card.appendChild(heading);
        if (!hit.meta) { return; }
        var about = document.createElement("div");
        about.className = "inspect-card__about md-body";
        about.innerHTML = hit.meta.about;              // rendered by the server
        card.appendChild(about);
        var more = Number(hit.meta.more) || 0;
        if (more > 0) {
            var link = document.createElement("a");
            link.className = "inspect-card__more";
            link.href = hit.name.getAttribute("href") || "";
            link.textContent = "\u2026 " + more + " more paragraph"
                + (more === 1 ? "" : "s") + " on its page";
            card.appendChild(link);
        }
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

    function attach(name) {
        if (cleanup) { cleanup(); }
        name.setAttribute("aria-describedby", "inspect-card");
        cleanup = FUI.autoUpdate(name, card, function () { place(name); });
    }

    function show(hit) {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        if (current === hit.name) { return; }
        if (current) { current.removeAttribute("aria-describedby"); }
        fill(hit);
        card.hidden = false;
        current = hit.name;
        currentPath = hit.path;
        currentKind = kindOf(hit.name);
        attach(hit.name);
    }

    function hide() {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        if (!current) { return; }
        card.hidden = true;
        card.textContent = "";
        current.removeAttribute("aria-describedby");
        current = null;
        if (cleanup) { cleanup(); cleanup = null; }
    }

    function scheduleHide() {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hide, 150);
    }

    // The pointer at rest on a name: every movement over it starts the pause again —
    // but a movement while a click is under way or just after one, the hand that
    // clicked still on the name it toggled, starts none.
    function restOn(name) {
        clearTimeout(showTimer);
        if (name === current) { clearTimeout(hideTimer); return; }
        if (pressed || performance.now() < quietUntil) { return; }
        showTimer = setTimeout(function () {
            if (pressed || resting !== name) { return; }
            // a refresh that came during the pause drew the name again, where the
            // pointer rests: the card is the one it drew's
            var target = grid.contains(name) ? name : drawnAgain(name);
            var hit = target ? cardOf(target) : null;
            if (!hit) { return; }
            resting = target;
            show(hit);
        }, REST_MS);
    }

    // --- the pointer ---
    grid.addEventListener("mousemove", function (e) {
        var name = nameOf(e.target);
        if (name !== resting) {
            resting = name;
            // off the name the card was for, for anywhere in the grid but the card
            if (current && name !== current) { scheduleHide(); }
        }
        if (name) { restOn(name); } else { clearTimeout(showTimer); }
    });
    grid.addEventListener("mouseleave", function (e) {
        resting = null;
        clearTimeout(showTimer);
        if (current && !(e.relatedTarget && card.contains(e.relatedTarget))) {
            scheduleHide();
        }
    });
    card.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    card.addEventListener("mouseleave", scheduleHide);

    // A click in the grid — on a name it opens or closes the node — takes the card
    // down and opens none for a moment after it.
    grid.addEventListener("pointerdown", function () {
        pressed = true;
        hide();
    });
    function released() {
        if (!pressed) { return; }
        pressed = false;
        quietUntil = performance.now() + AFTER_CLICK_MS;
    }
    document.addEventListener("pointerup", released, true);
    document.addEventListener("pointercancel", released, true);
    grid.addEventListener("click", function () {
        hide();
        quietUntil = performance.now() + AFTER_CLICK_MS;
    }, true);

    // --- keyboard focus ---
    // A name the keyboard reaches opens its card at once. The focus a click or a tap
    // gives a link is not the keyboard's: a click opens or closes the node, and on
    // touch the card is not offered.
    var lastInput = "keyboard";
    document.addEventListener("keydown", function (e) {
        lastInput = "keyboard";
        if (e.key === "Escape") { hide(); }
    }, true);
    grid.addEventListener("focusin", function (e) {
        if (lastInput !== "keyboard") { return; }
        var name = nameOf(e.target);
        if (!name || name !== e.target) { return; }
        var hit = cardOf(name);
        if (hit) { show(hit); }
    });
    grid.addEventListener("focusout", function (e) {
        if (e.relatedTarget && card.contains(e.relatedTarget)) { return; }
        if (current && e.target === current) { scheduleHide(); }
    });

    // --- touch: a tap is the node's toggle (tree.js), and the card is not offered;
    // a tap or a click anywhere else takes an open card down ---
    document.addEventListener("pointerdown", function (e) {
        lastInput = e.pointerType === "touch" ? "touch" : "pointer";
        if (current && !current.contains(e.target) && !card.contains(e.target)) {
            hide();
        }
    }, true);

    // Mark the names that have a card so the stylesheet can hint them with the help
    // cursor, again after each polled grid swap: a name whose node has an `about`
    // in the map or a title in its head, and whose pin is not being written.
    function markTriggers() {
        var titled = {};
        var titles = grid.querySelectorAll("[data-path] .node-title");
        for (var i = 0; i < titles.length; i++) {
            titled[titles[i].closest("[data-path]").getAttribute("data-path")] = true;
        }
        var writing = {};
        var editors = grid.querySelectorAll(EDITOR);
        for (var j = 0; j < editors.length; j++) {
            var owner = editors[j].closest(".tree-node");
            var row = owner ? owner.querySelector("[data-path]") : null;
            if (row) { writing[row.getAttribute("data-path")] = true; }
        }
        var names = grid.querySelectorAll(NAMES);
        for (var k = 0; k < names.length; k++) {
            var nameRow = rowOf(names[k]);
            var path = nameRow ? nameRow.getAttribute("data-path") : "";
            var has = !!path && !writing[path] && (!!titled[path]
                || Object.prototype.hasOwnProperty.call(META, path));
            names[k].classList.toggle("inspect-trigger", has);
        }
    }

    // After a swap the card's node has a new name: the one with the same path, of
    // the same kind — a chip, a head's toggle, the strip's name (ADR-0127 decision
    // 10). The card stays on it and says what the new fragment says; it goes down
    // when the node has left the page or has no card any more.
    function findName(path, kind) {
        var rows = grid.querySelectorAll(selectorFor(path));
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            if (kind === "chip") {
                if (row.classList.contains("tree-chip")) { return row; }
                continue;
            }
            if (row.classList.contains("tree-chip")) { continue; }
            var name = row.querySelector(kind === "strip" ? ".ls-strip__name"
                                                          : '[data-control="toggle"]');
            if (name) { return name; }
        }
        return null;
    }
    function drawnAgain(name) {
        var row = rowOf(name);
        return row ? findName(row.getAttribute("data-path"), kindOf(name)) : null;
    }
    function follow() {
        if (!current || grid.contains(current)) { return; }
        var again = findName(currentPath, currentKind);
        var hit = again ? cardOf(again) : null;
        if (!hit) { hide(); return; }
        current = again;
        fill(hit);
        attach(again);
    }

    readMeta();
    markTriggers();
    new MutationObserver(function () {
        readMeta();
        markTriggers();
        follow();
    }).observe(grid, { childList: true, subtree: true });
})();
