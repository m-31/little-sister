/* The drawer (ADR-0147 decisions 3 to 5): what a door opens on the wall and on a
 * node's page — ◇ on a head, a line's ◇ in its seat, a mark of what handles a part —
 * is the node's *Notes* tab, and here it opens over the page instead of in its
 * place: the tab's panel mode (`?panel=1`), the same page without the site's bar,
 * rail and band, framed in a modal dialog, `_drawer.html`. A click with a modifier, a
 * middle click, and a browser without the dialog keep the link's own meaning.
 *
 * Its head is the page's: the node's cue, its name and its state as the box clicked
 * says them, the state's marks without their links, then the node's page, its tab —
 * the address the door named — and ✕; under the name *updates paused*, which the
 * stylesheet shows on a page `poll.js` refreshes, while it waits. Its frame is made
 * at each opening and taken away at each close, so that a drawer is one page load
 * and leaves nothing in the browser's history. Opened from a head it opens at the
 * tab's top, from a line at its form on that line, from a mark at the block it marks,
 * the block's editor open; the focus goes into the frame, to the note of that form or
 * of that editor, and back to the door as the drawer closes — after a write, to the
 * same door once the refresh has drawn it again, or to its node's ◇ where what it
 * marked has gone.
 *
 * It holds the page (decision 4): modal, the page inert behind a shade light enough
 * to read it, cast by a hole over the box clicked, which follows the box as the page
 * scrolls or changes its size. At a desk the drawer stands at the right, 480 pixels
 * wide, and at the left where the box clicked would sit under it; on a phone it is a
 * sheet from the foot, and the page scrolls the box into the strip above it. Where
 * the box is taller than the room it has, the hole is over its head, or over the line
 * clicked. ✕, Escape — read in the frame as in the page — and a click on the page
 * close it, each through the question.
 *
 * The question (decision 5): where a field of a form in the frame differs from how it
 * was drawn — words typed, an end, a level, a deadline, a part chosen, a repeat's day
 * ticked — or the frame holds words a refused write or a preview gave back
 * (`data-ls-mine`), or a maintenance editor whose windows added or left out by hand
 * changed in place — by an ×, *Add an interval* or a day of its month
 * (`data-ls-dirty`, ADR-0150, landings 4 and 5) — a close asks *Discard what you
 * wrote?*, *Keep writing* focused, Escape keeping on writing; a link that would leave
 * the page, in the frame or in the head, asks the same. Nothing is kept in the
 * browser.
 *
 * A write from the drawer is a write from the tab: its form posts in the frame, and
 * nothing here reads or posts it. A submit names where its write comes back once it
 * has gone through, its form's `next`; the frame landing there is the write gone
 * through, which closes the drawer and brings the page up to date. Any other landing —
 * a refusal, a kind's conflict page, a way back to the tab — stays in the drawer, the
 * focus on why where there is one. A submit that opens another tab — a package's
 * button that drafts a ticket from the words (ADR-0148) — writes nothing here, so it
 * names nothing: the words stay, the question still asks before they are dropped,
 * and the frame's next landing is not taken for a write. Neither does a maintenance
 * editor's own button (`data-ls-nowrite`) — *Preview*, *Add an interval*, an ×,
 * *weekend*, *working week*, a day of its month and its paging — whose answer is the
 * editor back, drawn as a refusal is, and *Extend* and *End now* are writes as any
 * other: the drawer closes on them.
 *
 * The drawer says when it opens and when it closes, `ls:drawer` on the document, its
 * `detail` `{open, wrote}`. `poll.js` waits for it as for an editor, and once a write
 * has gone through brings the page up to date itself, which it says by cancelling
 * the event; a page that nothing refreshes, a leaf's, is loaded again.
 */
(function () {
    "use strict";

    var dialog = document.getElementById("ls-drawer");
    if (!dialog || typeof dialog.showModal !== "function") { return; }
    var panel = dialog.querySelector(".ls-drawer__panel");
    var head = dialog.querySelector(".ls-drawer__head");
    var title = dialog.querySelector(".ls-drawer__title");
    var nameSlot = dialog.querySelector(".ls-drawer__name");
    var stateSlot = dialog.querySelector(".ls-drawer__state");
    var toPage = dialog.querySelector("[data-to=\"page\"]");
    var toTab = dialog.querySelector("[data-to=\"tab\"]");
    var closer = dialog.querySelector(".ls-drawer__close");
    var lit = dialog.querySelector(".ls-drawer__lit");
    var ask = dialog.querySelector(".ls-drawer__ask");
    var discard = ask.querySelector("[data-ask=\"discard\"]");
    var keep = ask.querySelector("[data-ask=\"keep\"]");

    // What opens the drawer: a head's ◇, a line's ◇, a mark that is a door.
    var DOORS = "[data-control=\"door\"], .line-door, [data-door]";
    // Where the drawer is a sheet, as `overview.css` draws it.
    var PHONE = window.matchMedia("(max-width: 767.98px)");
    // The room kept between the box clicked and the edges of what it stands in.
    var MARGIN = 12;
    // How long a write's refresh may take before the focus is left where it is.
    var REFOCUS_MS = 20000;

    // The routes' own beginnings, as the server writes them: the tab's, which a door
    // names, and the page's, which the head links to.
    var NOTES = dialog.getAttribute("data-notes") || "/notes/";
    var STATUS = dialog.getAttribute("data-status") || "/status";

    var frame = null;      // the frame of this opening
    var opener = null;     // the door that opened it, which the focus goes back to
    var openerKey = null;  // what finds that door again once a refresh redrew it
    var lighted = null;    // what the hole is over
    var expected = null;   // where a submit from the frame lands once its write went through
    var wrote = false;     // a write from the drawer went through
    var drawn = false;     // the frame's first page has come
    var then = null;       // what the question does on *Discard*
    var writing = null;    // what had the focus in the frame when the question asked
    var pressed = null;    // where the pointer went down on the dialog
    var moving = false;    // a scroll or a resize waiting for the next frame
    // The page changing size under the drawer moves the box as a scroll does.
    var shifts = window.ResizeObserver ? new window.ResizeObserver(function () {
        follow();
    }) : null;

    // --- opening ------------------------------------------------------------------

    document.addEventListener("click", function (e) {
        if (e.defaultPrevented || e.button !== 0) { return; }
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
        var door = e.target.closest ? e.target.closest(DOORS) : null;
        if (!door || !door.hasAttribute("href") || dialog.contains(door)) { return; }
        e.preventDefault();
        open(door);
    });

    function open(door) {
        if (dialog.open) { return; }
        var address = new URL(door.getAttribute("href"), window.location.href);
        var node = door.closest(".tree-node[data-node]");
        var row = node ? node.querySelector(".status-card__head, .status-node__self") : null;
        opener = door;
        openerKey = { node: node ? node.getAttribute("data-node") : null,
                      href: door.getAttribute("href") };
        expected = null;
        wrote = false;
        drawn = false;
        then = null;
        writing = null;
        ask.hidden = true;
        head.inert = false;
        fillHead(row, address);
        var src = new URL(address.href);
        src.searchParams.set("panel", "1");
        frame = document.createElement("iframe");
        frame.className = "ls-drawer__frame";
        frame.title = "Notes of " + pathOf(address);
        frame.addEventListener("load", landed);
        frame.src = src.href;
        panel.appendChild(frame);
        dialog.showModal();
        // The page is told it waits before anything is read off it, so that the side,
        // the strip and the hole are the page's as it stands once it waits — the
        // pause is said in the drawer's head and the stamp keeps its width, so nothing
        // moves there, and the hole follows whatever else does. All of it in the one
        // task, so that nothing is drawn at the other side first; the strip needs the
        // sheet drawn, to know its height.
        say(true, false);
        if (PHONE.matches) { strip(door, node, row); } else { side(door, node, row); }
        drawLit();
        window.addEventListener("scroll", follow, { passive: true });
        window.addEventListener("resize", follow);
        if (shifts) { shifts.observe(document.body); }
    }

    // The head the page draws: the node's cue, its name and its state as the box
    // says them, and where the node's page and its tab are.
    function fillHead(row, address) {
        var path = pathOf(address);
        nameSlot.textContent = "";
        stateSlot.textContent = "";
        var name = row ? row.querySelector(".status-card__name, .status-node__name") : null;
        var cue = row ? row.querySelector(".status-cue") : null;
        var state = row ? row.querySelector(".status-card__state, .status-node__state") : null;
        if (cue) { nameSlot.appendChild(quiet(cue.cloneNode(true))); }
        nameSlot.appendChild(document.createTextNode(
            name ? name.textContent.replace(/\s+/g, " ").trim() : path));
        if (state) {
            var said = quiet(state.cloneNode(true));
            while (said.firstChild) { stateSlot.appendChild(said.firstChild); }
        }
        toTab.href = address.href;
        toTab.setAttribute("aria-label", "open the Notes tab of " + path);
        toPage.href = STATUS.replace(/\/$/, "") + "/" + rest(address.pathname);
        toPage.setAttribute("aria-label", "open the page of " + path);
    }

    // A copy of the box's words, as words: its links spans, its buttons gone, and
    // nothing that could take the focus or repeat an id.
    function quiet(copy) {
        if (copy.removeAttribute) { copy.removeAttribute("id"); }
        each(copy.querySelectorAll("[id]"), function (el) { el.removeAttribute("id"); });
        each(copy.querySelectorAll("[tabindex]"), function (el) { el.removeAttribute("tabindex"); });
        each(copy.querySelectorAll("button"), function (el) { el.remove(); });
        each(copy.querySelectorAll("a"), function (a) {
            var span = document.createElement("span");
            span.className = a.className;
            if (a.title) { span.title = a.title; }
            while (a.firstChild) { span.appendChild(a.firstChild); }
            a.parentNode.replaceChild(span, a);
        });
        return copy;
    }

    // The tab's address, past the route's beginning: the node's path as the address
    // writes it.
    function rest(pathname) {
        var at = pathname.indexOf(NOTES);
        return at < 0 ? pathname.replace(/^\/+/, "") : pathname.slice(at + NOTES.length);
    }

    function pathOf(address) {
        try { return decodeURIComponent(rest(address.pathname)); }
        catch (e) { return rest(address.pathname); }
    }

    // --- where it stands ------------------------------------------------------------

    // What the hole is over: the box clicked where it has room, otherwise its head, or
    // the line clicked — a node's page being no box of its own.
    function litOf(door, node, row, room) {
        var line = door.closest(".check-reason, .status-node__reason");
        var box = null;
        if (node && !node.hasAttribute("data-page-root")) {
            box = node.classList.contains("status-card") ? node
                : node.querySelector(":scope > .tree-hold > .tree-box");
        }
        var near = line || row || door;
        var choices = [box, near];
        for (var i = 0; i < choices.length; i++) {
            var r = choices[i] ? choices[i].getBoundingClientRect() : null;
            if (r && r.width && r.height && r.height <= room) { return choices[i]; }
        }
        return near;
    }

    // At a desk: at the right, unless the box would sit under it there — at the side
    // that leaves more of the box in sight, and never the one that hides where it
    // begins, its name or its words, while the other leaves that free.
    function side(door, node, row) {
        lighted = litOf(door, node, row, window.innerHeight - 2 * MARGIN);
        var wide = document.documentElement.clientWidth;
        var width = parseFloat(window.getComputedStyle(dialog)
            .getPropertyValue("--ls-drawer-width")) || 480;
        var box = lighted.getBoundingClientRect();
        var right = hidden(box, wide - width, wide);
        var left = hidden(box, 0, width);
        dialog.classList.toggle("is-left", left < right);
    }

    // How much of the box a drawer between `from` and `to` would hide: its width under
    // it, and the whole box over again where that covers its beginning.
    function hidden(box, from, to) {
        var under = Math.max(0, Math.min(box.right, to) - Math.max(box.left, from));
        var start = box.left + 2 * MARGIN;
        return under + (under > 0 && start >= from && start <= to ? box.width : 0);
    }

    // On a phone: the box scrolled into the strip above the sheet, below the bar.
    function strip(door, node, row) {
        var room = panel.getBoundingClientRect().top;
        var bar = document.querySelector(".ls-bar");
        var top = bar ? Math.max(0, bar.getBoundingClientRect().bottom) : 0;
        lighted = litOf(door, node, row, room - top - 2 * MARGIN);
        var by = lighted.getBoundingClientRect().top - (top + MARGIN);
        if (by) { window.scrollBy({ top: by, behavior: "instant" }); }
    }

    function drawLit() {
        moving = false;
        var r = lighted && lighted.isConnected ? lighted.getBoundingClientRect() : null;
        var s = lit.style;
        if (!r || !r.width || !r.height) {
            s.left = "50%"; s.top = "50%"; s.width = "0"; s.height = "0";
            return;
        }
        s.left = r.left + "px";
        s.top = r.top + "px";
        s.width = r.width + "px";
        s.height = r.height + "px";
        s.borderRadius = window.getComputedStyle(lighted).borderRadius;
    }

    // The hole follows the box as the page scrolls, the window changes, or the page
    // does.
    function follow() {
        if (moving) { return; }
        moving = true;
        window.requestAnimationFrame(function () {
            if (!dialog.open) { moving = false; return; }
            drawLit();
        });
    }

    // --- the frame ------------------------------------------------------------------

    function landed(e) {
        var f = e.target;
        if (f !== frame) { return; }
        var win;
        var doc;
        try {
            win = f.contentWindow;
            doc = f.contentDocument;
        } catch (err) {
            return;
        }
        if (!win || !doc || win.location.href === "about:blank") { return; }
        if (expected !== null) {
            var here = new URL(win.location.href);
            var went = here.origin === expected.origin && here.pathname === expected.pathname
                && here.search === expected.search;
            expected = null;
            if (went) {
                wrote = true;
                finish();
                return;
            }
        }
        hook(win, doc);
        if (!drawn) {
            drawn = true;
            focusAt(win, doc, f);
        } else {
            focusWhy(doc, f);
        }
    }

    function hook(win, doc) {
        // where the write comes back once it went through — but for a submit that
        // opens another tab, which writes nothing here (ADR-0148)
        doc.addEventListener("submit", function (e) {
            var form = e.target;
            if (elsewhere(form, e.submitter)) { return; }
            if (e.submitter && e.submitter.hasAttribute &&
                    e.submitter.hasAttribute("data-ls-nowrite")) {
                expected = null;
                return;
            }
            var next = form.elements ? form.elements.namedItem("next") : null;
            expected = next && next.value ? new URL(next.value, win.location.href) : null;
        });
        // Escape is the drawer's in the frame, read before the frame's own scripts
        // read it: an editor's Escape would drop its words without the question
        win.addEventListener("keydown", function (e) {
            if (e.key !== "Escape" && e.key !== "Esc") { return; }
            e.preventDefault();
            e.stopPropagation();
            escape();
        }, true);
        // a link that would leave the page asks before it drops what was written
        doc.addEventListener("click", function (e) {
            if (e.defaultPrevented || e.button !== 0) { return; }
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
            var link = e.target.closest ? e.target.closest("a[href]") : null;
            if (!link || !leaves(link, doc) || !dirty()) { return; }
            e.preventDefault();
            askThen(function () { window.location.assign(link.href); });
        });
    }

    // Whether a submit opens another tab rather than the frame's next page: the
    // target its button names, or its form's — the panel's forms say `_self`.
    function elsewhere(form, by) {
        var target = by && by.hasAttribute && by.hasAttribute("formtarget")
            ? by.getAttribute("formtarget") : form.getAttribute("target");
        return (target || "_self").toLowerCase() !== "_self";
    }

    // A link of the panel leaves the frame, `<base target="_top">`, but for the ways
    // back to the tab, which stay in it.
    function leaves(link, doc) {
        var target = link.getAttribute("target");
        if (target === null) {
            var base = doc.querySelector("base[target]");
            target = base ? base.getAttribute("target") : "_self";
        }
        target = target.toLowerCase();
        return target === "_top" || target === "_parent";
    }

    // The frame's first page: the focus to the note of the form or of the block's
    // editor it opens at, the block itself for a reader who may change nothing, or
    // the frame, at the tab's top.
    function focusAt(win, doc, f) {
        f.focus();
        var at = doc.getElementById("at");
        var target = at ? noteIn(at) : null;
        if (!at && /[?&]reason=/.test(win.location.search)) {
            var forms = doc.querySelectorAll(".ls-kind-form");
            for (var i = 0; i < forms.length && !target; i++) {
                if (forms[i].offsetParent !== null) { target = noteIn(forms[i]); }
            }
        }
        if (!target && at) {
            at.setAttribute("tabindex", "-1");
            target = at;
        }
        if (!target) { return; }
        try { target.focus({ preventScroll: true }); } catch (err) { target.focus(); }
        if (typeof target.setSelectionRange === "function") {
            target.setSelectionRange(target.value.length, target.value.length);
        }
    }

    function noteIn(root) {
        var notes = root.querySelectorAll("textarea[name=\"note\"], textarea[name=\"text\"]");
        for (var i = 0; i < notes.length; i++) {
            if (notes[i].offsetParent !== null) { return notes[i]; }
        }
        return null;
    }

    // A later page — a refusal, a kind's conflict page, the tab again — takes the
    // focus to why, where it says one.
    function focusWhy(doc, f) {
        f.focus();
        var why = doc.querySelector("[autofocus]") || doc.querySelector(".alert");
        if (!why) { return; }
        if (!why.hasAttribute("tabindex")) { why.setAttribute("tabindex", "-1"); }
        try { why.focus({ preventScroll: false }); } catch (err) { why.focus(); }
    }

    // --- the question ---------------------------------------------------------------

    // What was written and not sent: a field of a form in the frame that differs from
    // how it was drawn, or words a refused write gave back.
    function dirty() {
        if (wrote || !frame) { return false; }
        var doc;
        try { doc = frame.contentDocument; } catch (err) { return false; }
        if (!doc || !doc.body) { return false; }
        if (doc.body.hasAttribute("data-ls-mine")) { return true; }
        if (doc.querySelector("form[data-ls-dirty]")) { return true; }
        var fields = doc.querySelectorAll("form textarea, form input, form select");
        for (var i = 0; i < fields.length; i++) {
            if (changed(fields[i])) { return true; }
        }
        return false;
    }

    function changed(field) {
        if (field.tagName === "SELECT") {
            if (field.multiple) { return false; }
            var drawnAt = field.options.length ? 0 : -1;
            for (var i = 0; i < field.options.length; i++) {
                if (field.options[i].defaultSelected) { drawnAt = i; break; }
            }
            return field.selectedIndex !== drawnAt;
        }
        var type = (field.type || "").toLowerCase();
        if (/^(hidden|submit|button|reset|image|file)$/.test(type)) { return false; }
        if (type === "checkbox" || type === "radio") { return field.checked !== field.defaultChecked; }
        return field.value !== field.defaultValue;
    }

    function askThen(go) {
        then = go;
        writing = null;
        try { writing = frame ? frame.contentDocument.activeElement : null; } catch (err) { writing = null; }
        ask.hidden = false;
        head.inert = true;
        if (frame) { frame.inert = true; }
        keep.focus();
    }

    function answered() {
        then = null;
        ask.hidden = true;
        head.inert = false;
        if (frame) { frame.inert = false; }
    }

    function keepWriting() {
        var back = writing;
        writing = null;
        answered();
        if (!frame) { return; }
        frame.focus();
        if (back && typeof back.focus === "function" && back !== back.ownerDocument.body) {
            try { back.focus({ preventScroll: true }); } catch (err) { back.focus(); }
        }
    }

    discard.addEventListener("click", function () {
        var go = then;
        writing = null;
        answered();
        if (go) { go(); }
    });
    keep.addEventListener("click", keepWriting);

    // --- closing --------------------------------------------------------------------

    function requestClose() {
        if (!dialog.open || !ask.hidden) { return; }
        if (dirty()) {
            askThen(finish);
            return;
        }
        finish();
    }

    function escape() {
        if (!dialog.open) { return; }
        if (!ask.hidden) {
            keepWriting();
            return;
        }
        requestClose();
    }

    closer.addEventListener("click", requestClose);

    // Escape in the page, before the dialog reads it as a request to close, which
    // would close it without the question.
    window.addEventListener("keydown", function (e) {
        if (!dialog.open || (e.key !== "Escape" && e.key !== "Esc")) { return; }
        e.preventDefault();
        e.stopPropagation();
        escape();
    }, true);
    dialog.addEventListener("cancel", function (e) {
        e.preventDefault();
        escape();
    });
    // a close the browser made itself, without the question
    dialog.addEventListener("close", function () {
        if (frame || opener) { finish(); }
    });

    // A click on the page, which stands in the dialog's own area — a press and its
    // release both there, so that a drag out of the drawer closes nothing.
    dialog.addEventListener("pointerdown", function (e) { pressed = e.target; });
    dialog.addEventListener("click", function (e) {
        var outside = e.target === dialog && pressed === dialog;
        pressed = null;
        if (outside) { requestClose(); }
    });

    // The head's links leave the page: they ask first, as the frame's do.
    each([toPage, toTab], function (link) {
        link.addEventListener("click", function (e) {
            if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
            if (!dirty()) { return; }
            e.preventDefault();
            askThen(function () { window.location.assign(link.href); });
        });
    });

    function finish() {
        var did = wrote;
        expected = null;
        writing = null;
        answered();
        window.removeEventListener("scroll", follow);
        window.removeEventListener("resize", follow);
        if (shifts) { shifts.disconnect(); }
        var back = opener;
        var key = openerKey;
        opener = null;
        openerKey = null;
        lighted = null;
        if (dialog.open) { dialog.close(); }
        // the frame goes, and what it navigated in the history with it
        if (frame) {
            frame.remove();
            frame = null;
        }
        if (back && back.isConnected) {
            try { back.focus({ preventScroll: true }); } catch (err) { back.focus(); }
        }
        var refreshed = !say(false, did);
        if (!did) { return; }
        if (!refreshed) {
            window.location.reload();
            return;
        }
        if (key) { refocus(key); }
    }

    // Once the refresh has drawn the page again, the focus goes back to the same door,
    // or to its node's ◇ where what it marked has gone — unless it stands somewhere
    // already.
    function refocus(key) {
        var grid = document.getElementById("status-grid");
        if (!grid) { return; }
        var timer = null;
        function again() {
            grid.removeEventListener("ls:swapped", again);
            window.clearTimeout(timer);
            var active = document.activeElement;
            if (active && active !== document.body && grid.contains(active)) { return; }
            var found = doorOf(grid, key);
            if (found) {
                try { found.focus({ preventScroll: true }); } catch (err) { found.focus(); }
            }
        }
        grid.addEventListener("ls:swapped", again);
        timer = window.setTimeout(function () {
            grid.removeEventListener("ls:swapped", again);
        }, REFOCUS_MS);
    }

    function doorOf(root, key) {
        var scope = root;
        if (key.node !== null) {
            scope = root.querySelector(".tree-node[data-node=" + quoted(key.node) + "]");
            if (!scope) { return null; }
        }
        var doors = scope.querySelectorAll(DOORS);
        for (var i = 0; i < doors.length; i++) {
            if (doors[i].getAttribute("href") === key.href) { return doors[i]; }
        }
        var row = scope.querySelector(".status-card__head, .status-node__self");
        return row ? row.querySelector("[data-control=\"door\"]") : null;
    }

    function say(isOpen, did) {
        return document.dispatchEvent(new CustomEvent("ls:drawer", {
            cancelable: true, detail: { open: isOpen, wrote: did } }));
    }

    function quoted(value) {
        return "\"" + String(value).replace(/["\\]/g, "\\$&") + "\"";
    }

    function each(list, fn) {
        Array.prototype.forEach.call(list, fn);
    }

    // where the dialog opens, for a moment, before its frame takes the focus
    title.setAttribute("tabindex", "-1");
    title.setAttribute("autofocus", "");
})();
