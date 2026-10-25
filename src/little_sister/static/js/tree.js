/* The tree (ADR-0127): every node is closed, a chip, or open, a box, and a click on
 * it changes which; the tab's map (decisions 9 and 10) keeps what a viewer set
 * through the ~10s refresh and a reload.
 *
 * One script owns the map: one `sessionStorage` key, `ls-wall-map`, holding
 * `{v, mode, nodes}` — `mode` the band's button in force (`null`, "closed" or
 * "open") and `nodes` a node's entries by its path, each present only while it
 * differs from how the view draws the node on its own. A node's entries: `open`,
 * and beside a close `ok_since` and `ok_held`, the server's time of the first render
 * since the close that drew the node out of failure and whether a render six hundred
 * seconds or more after it still did (the close gives way to the next failure once it
 * has); `chips`, its ▤; `ok`, its healthy fold; and `lines`, its reason lines shown
 * past their budget. An entry of a kind this script no longer writes — `more`, a
 * level's surplus boxes shown, until the interactive wall's flip took *+N more* away —
 * is read by nothing. The map is read once on a load and written on every change;
 * storage that is missing, unreadable or full leaves it in memory for the page's
 * life, never an error. A new tab starts as configured, since `sessionStorage` is the
 * tab's; nothing is written to a cookie.
 *
 * How a node looks is worked out from the server's markers alone (`data-state`,
 * `data-chips`, `data-ok`, `data-swq`, `data-budget`, `data-failing`,
 * `data-healthy`, `data-page-root`) and the map, never from a status — the rules of
 * backlog #91 §7.9, the one that decided written on the node as `data-why`. A
 * node's page draws its node as a frame, `data-page-root`, always open: its level
 * is the page's grid, whose cards are its children, so its ▤ and its funnel work
 * them by the node's own entries — the ones its box carries on the wall — and its
 * funnel folds its own healthy lines, which the page lists in full (§3.5). The
 * markup carries both faces of every node: `.tree-chip` and, in `.tree-hold`, the
 * box; this script shows one and hides the other — the box's wrapper
 * `hidden="until-found"` while the node is closed, so the browser's find reaches
 * what is beneath a chip and `beforematch` opens it as a click would — and re-forms
 * each level by `data-order`: consecutive closed children stand in a `.tree-run`, an
 * open child in its place between runs, so a node opens where it stood.
 *
 * Around each swap `poll.js` calls `before(container)` just before it replaces the
 * grid and `apply(container)` directly after, before anything paints: the map is put
 * back on the new markup, the keyboard's focus goes back to the same control of the
 * same node — `[data-control]` names the control and its `[data-path]` the node —
 * without scrolling, the window scrolls by what
 * the node nearest its top moved, so that it shows what it showed, and the open
 * inspection card finds its node's new element by itself (`inspect.js`). One
 * MutationObserver stays as a fallback for a swap `poll.js` did not make. On a load
 * `tree-pending.js` has hidden the grid while the map holds anything; the first apply
 * shows it.
 *
 * The head's row (decision 3) is measured here: a box shown — after a swap, by a click,
 * a find or the map, on a resize and once the fonts have settled — gets its lines'
 * overflow read, which shows *⌄ all N* beneath them, and its row read as it would be
 * with the title gone, from which the node's actions the row has no room for fold
 * behind ⋯ — never one alone where the state's line keeps it in the row — and, where
 * the name would still be cut or one action fold alone, the state cluster goes beneath
 * the row (`.is-state-below`): beside the name's last line where the name broke anyway
 * and the state touches neither it nor the toolbar (`.is-state-beside`), on a line of
 * its own where it would. The grid is planned first (`dashboard-layout.js`), so a row
 * is read at the width its card is drawn at; and a refresh reads only a row the server
 * drew otherwise, or that stands at another width, than one read before — the rest are
 * drawn from what was read of them. A head's controls — its icons, ↗ first, then its
 * actions and ⋯ — are one toolbar with one tab stop, walked with the arrow keys, which
 * the look `head_buttons` places (ADR-0029): right after the name; on a line of its own
 * beneath the row, which wraps there, so that no row is read; at the row's end, where
 * the pointer's click on an open head's name follows its link to the node's page and
 * the keyboard's Enter opens and closes the node as before; or right after the name
 * with the name a link as at the end (`pointer-name`). Which control holds the stop
 * is kept by node in memory, never in the map, and given back after a swap. An
 * admin's ‖ clones the page's one `template#pin-editor` into the node's box, where the
 * pin's block will stand, and Cancel or Escape take the clone away again; the ringed
 * check clones `template#ack-editor` the same way, with the digest of the failures
 * it marks seen (ADR-0142).
 *
 * On the kiosk (`<body data-ls-layout="kiosk">`) the map lives in memory and never in
 * `sessionStorage`: five minutes after the last pointer, touch, key or wheel it is
 * emptied and applied again, which brings the first look back with a bookmark's
 * `depth=` — a kiosk's tab stays open for months. A tap toggles a node there as
 * anywhere; its heads carry no icons.
 *
 * Bound once via event delegation on #status-grid, so the handlers survive the ~10s
 * grid innerHTML swaps (the inspection-popover pattern, ADR-0019).
 */
(function () {
    "use strict";

    // The grid the refresh swaps, or on a leaf's own page, which is not polled, what
    // holds the frame the page draws its node in (backlog #91 §3.5): its funnel's
    // entry is the map's like any other.
    var grid = document.getElementById("status-grid") || document.querySelector(".node-page");
    if (!grid) { return; }

    var KEY = "ls-wall-map";
    var VERSION = 1;
    var PENDING = "ls-tree-pending";
    // Put on <html> once the map is applied: until then the stylesheet folds what the
    // configured fold folds (`data-fold-drawn`, ADR-0128), so it stands from the first
    // paint; from then on this script folds and shows it, a viewer's word among it.
    var READY = "ls-tree-ready";
    // Put there with it: under the look `boxes: packed` (ADR-0138) the stylesheet
    // hides the wall until the boxes have taken their columns, so that the first paint
    // never stands them in rows for the packing to move.
    var DRAWN = "ls-boxes-drawn";
    var KIOSK = document.body.getAttribute("data-ls-layout") === "kiosk";
    // How long a kiosk keeps what somebody touched, from the last input.
    var KIOSK_IDLE_MS = 5 * 60 * 1000;
    // Overflow beyond the line budget smaller than this (px) isn't worth a chevron —
    // keeps a block that spills by a rounding sliver from sprouting one.
    var CLIP_SLOP = 8;
    // A close holds for its node's incident: once a render six hundred seconds of the
    // server's clock after the first that drew the node out of failure still does,
    // the next failure opens the node again (ADR-0127 decision 9).
    var INCIDENT_S = 600;
    // A find's reveal is provisional this long: a later reveal outside it within the
    // window closes what the earlier one opened (decision 11).
    var REVEAL_MS = 2000;
    // How far a pointer may travel between its press and its click and still toggle:
    // past it the viewer was dragging, selecting the head's text.
    var DRAG_PX = 6;
    // The controls in a head that are not the head: a click on them never toggles.
    // The state cluster among them is the head — a click on its word toggles.
    var OWN_CONTROLS = ".node-icons, .node-actions, .node-more, .node-actions-menu, "
        + ".maintenance-pip, .pin-setter, .rule-setter, .ack-setter, .rule-block, "
        + ".reason-pin, .reason-ack, "
        + ".reason-block, .reason-more, .own-lines, .reason-quiet-count, .tree-ok, "
        + "details, form";
    // A head's controls, in the toolbar's order: what the arrow keys walk and the
    // keyboard's one stop is among.
    var TOOLBAR_CONTROLS = ".node-actions > a, .node-actions > button, .node-actions > form button, "
        + ".node-more, .maintenance-pip, .node-icons > a, .node-icons > button";
    // How long a resize may go on before the heads are measured again (ms): short,
    // so the rows settle with the layout, and coalesced, so a drag measures once.
    var RESIZE_MS = 50;
    // A row's parts are read in fractional pixels and laid out in them: this much
    // more is given back than the row was read to overflow by, so a rounding never
    // leaves a row a pixel short, which would break its name.
    var SLACK_PX = 2;
    // The look `chip_runs: aligned` (`looks.py`): a level's runs share one column
    // width, which this script measures (the runs' width, below); wrapped runs need
    // none, and the server sizes nothing for them.
    var ALIGNED = document.body.getAttribute("data-ls-chip-runs") === "aligned";
    // How far past the rest a level's widest name sizes its columns: at most this
    // many times its 90th-percentile name, as the server's estimate has it
    // (`app.CHIP_NAME_BOUND`); a name past it wraps inside its column.
    var NAME_BOUND = 1.5;

    // --- the map ----------------------------------------------------------------------

    function empty() { return { v: VERSION, mode: null, nodes: {} }; }

    function read() {
        if (KIOSK) { return empty(); }
        var raw = null;
        try { raw = window.sessionStorage.getItem(KEY); } catch (e) { return empty(); }
        if (!raw) { return empty(); }
        var got;
        try { got = JSON.parse(raw); } catch (e) { return empty(); }
        // a map of another version is dropped whole, and the tab starts as configured
        if (!got || got.v !== VERSION || typeof got.nodes !== "object" || !got.nodes) {
            return empty();
        }
        return {
            v: VERSION,
            mode: got.mode === "closed" || got.mode === "open" ? got.mode : null,
            nodes: got.nodes
        };
    }

    var map = read();

    function write() {
        if (KIOSK) { return; }
        try {
            if (map.mode === null && Object.keys(map.nodes).length === 0) {
                window.sessionStorage.removeItem(KEY);
            } else {
                window.sessionStorage.setItem(KEY, JSON.stringify(map));
            }
        } catch (e) { /* no storage: the map stays in memory for the page's life */ }
    }

    function entryOf(path) { return map.nodes[path] || {}; }

    function held(path, kind) {
        var entry = map.nodes[path];
        return !!(entry && entry[kind]);
    }

    // Set one of a node's entries, or remove it (`undefined`): an entry is present
    // only while it differs from how the view draws the node on its own.
    function hold(path, kind, value) {
        var entry = map.nodes[path] || {};
        if (value === undefined) { delete entry[kind]; } else { entry[kind] = value; }
        if (Object.keys(entry).length) { map.nodes[path] = entry; }
        else { delete map.nodes[path]; }
        write();
    }

    function quoted(value) {
        return '"' + String(value).replace(/["\\]/g, "\\$&") + '"';
    }

    function escaped(value) {
        return (window.CSS && CSS.escape) ? CSS.escape(value) : quoted(value);
    }

    // --- the markup --------------------------------------------------------------------

    function nodeOf(el) { return el && el.closest ? el.closest(".tree-node") : null; }

    function isCard(node) { return node.classList.contains("status-card"); }

    // The node a page is about: its frame, always open, whose level is the page's
    // grid of cards (backlog #91 §3.5).
    function isPageRoot(node) { return node.hasAttribute("data-page-root"); }

    function pathOf(node) { return node.getAttribute("data-node"); }

    // The one direct child of `el` with the class `name`, or null — the faces and
    // the heads are direct children, and walking them costs a wall of nodes far
    // less than a selector each.
    function own(el, name) {
        if (!el) { return null; }
        var kids = el.children;
        for (var i = 0; i < kids.length; i++) {
            if (kids[i].classList.contains(name)) { return kids[i]; }
        }
        return null;
    }

    // A node's parts, found once per pass: its chip (none on a card), its box's
    // wrapper, the box, the head row, the head's controls and among them its
    // icons, its children's level and the healthy fold's mark.
    var parts = new Map();

    function partsOf(node) {
        var found = parts.get(node);
        if (found) { return found; }
        var card = isCard(node);
        var hold = own(node, "tree-hold");
        var box = card ? own(hold, "status-panel") : own(hold, "tree-box");
        // a page's frame: its head is the node's own box, the row atop it, and its
        // level the page's grid
        var root = !card && isPageRoot(node);
        var lead = root ? own(box, "viewed-head") : null;
        var head = card ? own(node, "status-card__head")
                 : own(root ? lead : box, "status-node__self");
        var controls = own(head, "node-controls");
        found = {
            card: card,
            chip: card || root ? null : own(node, "tree-chip"),
            hold: hold,
            box: box,
            lead: lead,
            head: head,
            controls: controls,
            icons: own(controls, "node-icons"),
            kids: own(box, root ? "status-grid" : "tree-kids"),
            mark: own(card ? hold : box, "tree-ok"),
            toggle: head && !root ? head.querySelector("[data-control=\"toggle\"]") : null
        };
        parts.set(node, found);
        return found;
    }

    function chipOf(node) { return partsOf(node).chip; }

    function holdOf(node) { return partsOf(node).hold; }

    function headOf(node) { return partsOf(node).head; }

    function toggleOf(node) { return partsOf(node).toggle; }

    function iconOf(node, kind) {
        var icons = partsOf(node).icons;
        if (!icons) { return null; }
        for (var i = 0; i < icons.children.length; i++) {
            if (icons.children[i].getAttribute("data-control") === kind) {
                return icons.children[i];
            }
        }
        return null;
    }

    // the level a node's children stand in, and a level's children
    function kidsOf(node) { return partsOf(node).kids; }

    function childrenOf(level) {
        var found = [];
        var items = level.children;
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (item.classList.contains("tree-node")) { found.push(item); }
            else if (isWrapper(item)) {
                for (var j = 0; j < item.children.length; j++) {
                    if (item.children[j].classList.contains("tree-node")) {
                        found.push(item.children[j]);
                    }
                }
            }
        }
        return found;
    }

    function levelOf(node) {
        var parent = node.parentElement;
        if (parent && isWrapper(parent)) { parent = parent.parentElement; }
        return parent && parent.classList.contains("tree-kids") ? parent : null;
    }

    // the node above a node: a box's, or on a node's page a card's, the page's frame
    // — on the wall a card has none
    function parentOf(node) {
        var level = levelOf(node);
        if (level) { return nodeOf(level); }
        if (!isCard(node) || !node.parentElement) { return null; }
        var frame = nodeOf(node.parentElement);
        return frame && isPageRoot(frame) ? frame : null;
    }

    function isOpen(node) { return node.getAttribute("data-state-now") === "open"; }

    // --- the look (backlog #91 §7.9) ---------------------------------------------------

    function anyOpenBeneath(path) {
        var prefix = path + "/";
        for (var key in map.nodes) {
            if (key.indexOf(prefix) === 0 && map.nodes[key].open === true) { return true; }
        }
        return false;
    }

    // How a node looks: open or closed, and the rule that decided it. `ownEntry`
    // false asks how the view draws the node on its own, which is what an entry
    // must differ from to be kept.
    function lookOf(node, ownEntry) {
        // the node a page is about is always open: the page is its window
        if (isPageRoot(node)) { return { open: true, why: "page" }; }
        var path = pathOf(node);
        var entry = entryOf(path);
        if (ownEntry !== false && typeof entry.open === "boolean") {
            return { open: entry.open, why: "entry" };
        }
        if (map.mode === "closed" && anyOpenBeneath(path)) {
            return { open: true, why: "kept" };
        }
        if (map.mode === null) {
            if (node.hasAttribute("data-swq")) { return { open: true, why: "swq" }; }
            if (node.hasAttribute("data-budget")) { return { open: true, why: "budget" }; }
        }
        var parent = parentOf(node);
        if (parent) {
            var above = entryOf(pathOf(parent));
            if (typeof above.chips === "boolean") {
                return { open: !above.chips, why: "parent" };
            }
        }
        if (map.mode === "closed") { return { open: false, why: "mode" }; }
        if (map.mode === "open") { return { open: true, why: "mode" }; }
        var drawnOpen = node.getAttribute("data-state") === "open";
        if (parent && isPageRoot(parent) && drawnOpen) {
            // the page's rule: its node's children open as it arrives (decision 8),
            // which the server draws; a `depth=` closing them is the viewer's word
            return { open: true, why: "page" };
        }
        return { open: drawnOpen, why: "drawn" };
    }

    // Whether a node's healthy ones are folded, and whether by the viewer's press.
    function foldOf(node) {
        var entry = entryOf(pathOf(node));
        if (typeof entry.ok === "boolean") { return { folded: entry.ok, pressed: entry.ok }; }
        if (map.mode === "open") { return { folded: false, pressed: false }; }
        return { folded: node.getAttribute("data-ok") === "true", pressed: false };
    }

    // ▤ as the view draws it on its own: the mode's, or what the server drew.
    function drawnChips(node) {
        if (map.mode === "closed") { return "true"; }
        if (map.mode === "open") { return "false"; }
        return node.getAttribute("data-chips") || "false";
    }

    // --- the faces ---------------------------------------------------------------------

    // The wrapper a find is revealing right now: the browser takes its `hidden` off
    // itself once `beforematch` has been handled, and a script that takes it off
    // during the event ends the reveal there — Chromium then reveals no ancestor
    // above it (backlog #91 §7.10).
    var revealing = null;

    function showFace(node, open, why) {
        node.setAttribute("data-state-now", open ? "open" : "closed");
        node.setAttribute("data-why", why);
        var hold = holdOf(node);
        if (hold && hold !== revealing) {
            if (open) { hold.removeAttribute("hidden"); }
            else { hold.setAttribute("hidden", "until-found"); }
        }
        var chip = chipOf(node);
        if (chip) {
            if (open) { chip.setAttribute("hidden", ""); } else { chip.removeAttribute("hidden"); }
            chip.setAttribute("role", "button");
            chip.setAttribute("aria-expanded", open ? "true" : "false");
        }
        if (isCard(node)) { node.classList.toggle("is-closed", !open); }
        var toggle = toggleOf(node);
        if (toggle) {
            toggle.setAttribute("role", "button");
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
        }
    }

    // ▤'s pressed state, from the children's faces; and its dot.
    function drawChips(node) {
        var button = iconOf(node, "chips");
        if (!button) { return; }
        var level = kidsOf(node);
        var kids = level ? childrenOf(level) : [];
        var closed = 0;
        for (var i = 0; i < kids.length; i++) { if (!isOpen(kids[i])) { closed += 1; } }
        var state = kids.length && closed === kids.length ? "true"
                  : closed === 0 ? "false" : "mixed";
        button.setAttribute("aria-pressed", state);
        var words = state === "true" ? "Open the children" : "Fold the children to chips";
        button.setAttribute("title", words);
        button.setAttribute("aria-label", words);
        button.classList.toggle("is-changed", typeof entryOf(pathOf(node)).chips === "boolean");
    }

    // The healthy fold (decision 4): what is marked healthy folds behind *✓ +N ok*;
    // a child that claims `show_when_quiet`, and a claiming node's own lines, only
    // under a fold the viewer pressed (decision 5).
    function drawFold(node) {
        var fold = foldOf(node);
        var claims = node.hasAttribute("data-swq");
        var count = 0;
        var level = kidsOf(node);
        var kids = level ? childrenOf(level) : [];
        for (var i = 0; i < kids.length; i++) {
            var kid = kids[i];
            if (!kid.hasAttribute("data-healthy")) { continue; }
            var folds = fold.folded && (fold.pressed || !kid.hasAttribute("data-swq"));
            if (folds) { kid.setAttribute("hidden", ""); count += 1; }
            else { kid.removeAttribute("hidden"); }
        }
        var p = partsOf(node);
        var lines = healthyLinesOf(p);
        for (var j = 0; j < lines.length; j++) {
            var hides = fold.folded && (fold.pressed || !claims);
            if (hides) { lines[j].setAttribute("hidden", ""); count += 1; }
            else { lines[j].removeAttribute("hidden"); }
        }
        var button = iconOf(node, "ok");
        if (button) {
            var would = Number(button.getAttribute(
                fold.pressed ? "data-n-pressed" : "data-n")) || 0;
            var n = fold.folded ? count : Number(button.getAttribute("data-n-pressed")) || would;
            var words = (fold.folded ? "Show the " : "Fold the ") + n + " healthy ones";
            button.setAttribute("aria-pressed", fold.folded ? "true" : "false");
            button.setAttribute("title", words);
            button.setAttribute("aria-label", words);
            button.classList.toggle("is-changed",
                                    typeof entryOf(pathOf(node)).ok === "boolean");
        }
        var mark = p.mark;
        if (mark) {
            if (fold.folded && count) {
                mark.textContent = "\u2713 +" + count + " ok";
                mark.setAttribute("aria-pressed", "true");
                mark.setAttribute("aria-label", "show the " + count + " healthy ones");
                mark.removeAttribute("hidden");
            } else {
                mark.setAttribute("hidden", "");
            }
        }
    }

    // A node's own healthy lines, which its fold folds: a box's block, after its
    // head's row; or the lines a node's page lists in full, in its frame's head or in
    // the one card of `depth=0` (`_own_lines.html`), which nothing clamps.
    function healthyLinesOf(p) {
        var block = own(p.box, "reason-block");
        if (block) { return block.querySelectorAll(".status-node__reason[data-healthy]"); }
        var listed = own(p.lead || p.box, "own-lines");
        return listed ? listed.querySelectorAll(":scope > .check-reason[data-healthy]") : [];
    }

    // --- a level's runs ----------------------------------------------------------------

    function byOrder(a, b) {
        return Number(a.getAttribute("data-order")) - Number(b.getAttribute("data-order"));
    }

    // What a level should hold, item by item: an open node on its own, consecutive
    // closed nodes in one run.
    function groupsOf(kids) {
        var want = [];
        var run = null;
        for (var i = 0; i < kids.length; i++) {
            if (isOpen(kids[i])) { want.push({ kind: "node", nodes: [kids[i]] }); run = null; }
            else {
                if (!run) { run = { kind: "run", nodes: [] }; want.push(run); }
                run.nodes.push(kids[i]);
            }
        }
        return want;
    }

    function isWrapper(el) {
        return el.classList.contains("tree-run") || el.classList.contains("tree-solo");
    }

    // Whether the level already has the shape `want` describes, so nothing moves.
    function sameShape(level, want) {
        var at = 0;
        for (var i = 0; i < level.children.length; i++) {
            var item = level.children[i];
            var group = want[at++];
            if (!group) { return false; }
            if (item.classList.contains("tree-node")) {
                if (group.kind !== "node" || group.nodes[0] !== item) { return false; }
            } else if (item.classList.contains("tree-solo")) {
                if (group.kind !== "node" || item.children.length !== 1
                        || item.children[0] !== group.nodes[0]) { return false; }
            } else if (item.classList.contains("tree-run")) {
                if (group.kind !== "run" || item.children.length !== group.nodes.length) {
                    return false;
                }
                for (var j = 0; j < group.nodes.length; j++) {
                    if (item.children[j] !== group.nodes[j]) { return false; }
                }
            } else { return false; }
        }
        return at === want.length;
    }

    // One top-level item of a level, built by moving its nodes: an open node itself,
    // or a run of closed nodes — the run they stand in already where that holds
    // exactly them, else a new one. Never `keep`, the pivot's own wrapper.
    function built(group, keep) {
        if (group.kind === "node") { return group.nodes[0]; }
        var parent = group.nodes[0].parentElement;
        if (parent && parent !== keep && parent.classList.contains("tree-run")
                && parent.children.length === group.nodes.length) {
            var same = true;
            for (var i = 0; i < group.nodes.length; i++) {
                if (parent.children[i] !== group.nodes[i]) { same = false; break; }
            }
            if (same) { return parent; }
        }
        var wrapper = document.createElement("div");
        wrapper.className = "tree-run";
        for (var j = 0; j < group.nodes.length; j++) { wrapper.appendChild(group.nodes[j]); }
        return wrapper;
    }

    // Re-form a level by `data-order`: consecutive closed children in one run, an open
    // child in its place between runs. `pivot` is a node that must not move — the one
    // a find revealed, whose match the browser is about to scroll to (a node taken
    // out of the DOM and put back collapses the find's range) — so its neighbours
    // move around it: the wrapper it stands in is kept and takes its group, as a run
    // or, holding the one open node, as `.tree-solo`, which `overview.css` draws
    // without a box of its own. Nothing moves where the level has the shape already.
    function reform(level, pivot) {
        // a page's cards close in their places, as the wall's do: no runs among them
        if (!level.classList.contains("tree-kids")) { return; }
        var want = groupsOf(childrenOf(level).sort(byOrder));
        if (sameShape(level, want)) { return; }
        var anchor = null;
        var at = -1;
        if (pivot && levelOf(pivot) === level) {
            for (var g = 0; g < want.length; g++) {
                if (want[g].nodes.indexOf(pivot) >= 0) { at = g; }
            }
            var group = want[at];
            var wrapper = pivot.parentElement;
            if (wrapper === level && group.kind === "run") {
                // a direct child cannot gain a wrapper without moving: it stands on
                // its own, and its would-be neighbours in runs beside it
                var i = group.nodes.indexOf(pivot);
                var pieces = [];
                if (i > 0) { pieces.push({ kind: "run", nodes: group.nodes.slice(0, i) }); }
                pieces.push({ kind: "node", nodes: [pivot] });
                if (i + 1 < group.nodes.length) {
                    pieces.push({ kind: "run", nodes: group.nodes.slice(i + 1) });
                }
                want.splice.apply(want, [at, 1].concat(pieces));
                if (i > 0) { at += 1; }
                anchor = pivot;
            } else if (wrapper === level) {
                anchor = pivot;
            } else {
                anchor = wrapper;
                anchor.className = group.kind === "run" ? "tree-run" : "tree-solo";
                var parking = document.createDocumentFragment();
                var strays = Array.prototype.slice.call(anchor.children);
                for (var s = 0; s < strays.length; s++) {
                    if (group.nodes.indexOf(strays[s]) < 0) { parking.appendChild(strays[s]); }
                }
                var seen = false;
                for (var m = 0; m < group.nodes.length; m++) {
                    var member = group.nodes[m];
                    if (member === pivot) { seen = true; continue; }
                    if (!seen) { anchor.insertBefore(member, pivot); }
                    else { anchor.appendChild(member); }
                }
                // the parked nodes are placed with their groups below
            }
        }
        var before = document.createDocumentFragment();
        var after = document.createDocumentFragment();
        for (var w = 0; w < want.length; w++) {
            if (w === at) { continue; }
            (at < 0 || w < at ? before : after).appendChild(built(want[w], anchor));
        }
        // what is left in the level — emptied wrappers, nothing else — goes
        var items = Array.prototype.slice.call(level.children);
        for (var x = 0; x < items.length; x++) {
            if (items[x] !== anchor && items[x].parentElement === level) {
                level.removeChild(items[x]);
            }
        }
        if (anchor) {
            level.insertBefore(before, anchor);
            if (anchor.nextSibling) { level.insertBefore(after, anchor.nextSibling); }
            else { level.appendChild(after); }
        } else {
            level.appendChild(before);
        }
    }

    // --- a box's lines: *⌄ all N* ---------------------------------------------------------

    // The button after a block, drawn by the server `hidden` with its total where
    // the lines are more than the budget, which this script shows while the lines
    // overflow their budget or stand open; a block of fewer lines that overflows
    // because they wrap gets one drawn here, when it is first needed.
    function moreOf(block, wanted) {
        var next = block.nextElementSibling;
        if (next && next.classList.contains("reason-more")) { return next; }
        if (!wanted) { return null; }
        var button = document.createElement("button");
        button.type = "button";
        button.className = "reason-more";
        button.setAttribute("data-control", "lines");
        button.setAttribute("aria-expanded", "false");
        if (block.id) { button.setAttribute("aria-controls", block.id); }
        button.setAttribute("hidden", "");
        quietly(function () { block.parentNode.insertBefore(button, block.nextSibling); });
        return button;
    }

    function blockOf(button) {
        var previous = button.previousElementSibling;
        return previous && previous.classList.contains("reason-block") ? previous : null;
    }

    // Where each open block stands scrolled, by its node's path, for the tab's life. The
    // lines *⌄ all N* opens scroll inside a box no taller than about half a window
    // (backlog #91); the swap draws them anew, at their first line, and this puts each
    // back where its viewer left it, as poll.js does a table's left edge. A reload
    // starts them at the top, as it does a table.
    var scrolled = {};

    document.addEventListener("scroll", function (e) {
        var block = e.target;
        if (!block.classList || !block.classList.contains("reason-block")
                || !block.classList.contains("is-open")) { return; }
        scrolled[block.getAttribute("data-reason-node")] = block.scrollTop;
    }, { capture: true, passive: true });

    // The name a block's region is called by: its box's, as the head shows it.
    function linesOf(block) {
        var box = block.closest(".tree-box, .status-card");
        var name = box ? box.querySelector(".status-node__name, .status-card__name") : null;
        var said = name ? name.textContent.replace(/\s+/g, " ").trim() : "";
        if (said) { return said; }
        var path = block.getAttribute("data-reason-node") || "";
        return path.slice(path.lastIndexOf("/") + 1);
    }

    // An open block whose lines pass its height scrolls inside itself: a region the
    // keyboard reaches and a screen reader names. Any other block is neither, and a
    // closed one stands at its first line again, which is what its budget shows. Only
    // writes, and no read: the blocks are drawn in one pass after one measure.
    function scrollArea(block, open, scrolls) {
        var path = block.getAttribute("data-reason-node");
        if (open && scrolls) {
            block.setAttribute("role", "region");
            block.setAttribute("tabindex", "0");
            block.setAttribute("aria-label", "All " + (block.getAttribute("data-reason-total")
                || "") + " lines of " + linesOf(block));
            return;
        }
        block.removeAttribute("role");
        block.removeAttribute("tabindex");
        block.removeAttribute("aria-label");
        if (!open && Object.prototype.hasOwnProperty.call(scrolled, path)) {
            delete scrolled[path];
            block.scrollTop = 0;
        }
    }

    // An open block back where its viewer left it, once every block is drawn.
    function scrollBack(block) {
        var path = block.getAttribute("data-reason-node");
        if (block.classList.contains("is-open") && scrolled[path]) {
            block.scrollTop = scrolled[path];
        }
    }

    // A block inside a closed node's wrapper has no layout to measure, and a box
    // hidden at the swap measures nothing (backlog #91 §7.4): it is measured once
    // the box is shown.
    function shown(el) {
        return !el.closest(".tree-hold[hidden]");
    }

    function applyLines(block) {
        if (!shown(block)) { return; }
        var path = block.getAttribute("data-reason-node");
        var open = held(path, "lines");
        block.classList.toggle("is-open", open);
        // Whether the lines overflow their budget is only measurable here (the clamp
        // is CSS). Measured while folded; an open block keeps its button so it can
        // be folded again, and scrolls where its lines pass its height.
        var over = block.scrollHeight - block.clientHeight;
        drawLines(block, open, !open && over > CLIP_SLOP, open && over > 1);
        scrollBack(block);
    }

    // Every shown block at once: the writes first, then every measure in one pass,
    // then the writes that follow — one layout for the wall, not one per block.
    function applyAllLines(blocks) {
        var pending = [];
        var i;
        for (i = 0; i < blocks.length; i++) {
            if (!shown(blocks[i])) { continue; }
            var open = held(blocks[i].getAttribute("data-reason-node"), "lines");
            blocks[i].classList.toggle("is-open", open);
            pending.push({ block: blocks[i], open: open });
        }
        for (i = 0; i < pending.length; i++) {
            var block = pending[i].block;
            var over = block.scrollHeight - block.clientHeight;
            pending[i].clipped = !pending[i].open && over > CLIP_SLOP;
            pending[i].scrolls = pending[i].open && over > 1;
        }
        for (i = 0; i < pending.length; i++) {
            drawLines(pending[i].block, pending[i].open, pending[i].clipped,
                      pending[i].scrolls);
        }
        for (i = 0; i < pending.length; i++) {
            if (pending[i].scrolls) { scrollBack(pending[i].block); }
        }
    }

    function drawLines(block, open, clipped, scrolls) {
        block.classList.toggle("is-clipped", clipped);
        scrollArea(block, open, scrolls);
        var button = moreOf(block, open || clipped);
        if (!button) { return; }
        if (open || clipped) {
            var total = block.getAttribute("data-reason-total") || "";
            button.textContent = open ? "⌃ less" : "⌄ all " + total;   // ⌃ / ⌄
            button.setAttribute("aria-expanded", open ? "true" : "false");
            button.removeAttribute("hidden");
        } else {
            button.setAttribute("hidden", "");
        }
    }

    // --- the head's row (decision 3) ----------------------------------------------------

    // The controls of a head's toolbar, in its order, folded actions left out.
    function controlsOf(head) {
        var p = own(head, "node-controls");
        if (!p) { return []; }
        var all = p.querySelectorAll(TOOLBAR_CONTROLS);
        var found = [];
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            if (el.closest(".node-actions-menu") || el.hasAttribute("hidden")) { continue; }
            var item = el.closest(".node-actions > *");
            if (item && item.classList.contains("is-folded")) { continue; }
            found.push(el);
        }
        return found;
    }

    // The node's actions as items of the rail: each direct child of `.node-actions`,
    // an `<a>` or a `<form>` around a button.
    function actionsOf(head) {
        var p = own(head, "node-controls");
        var rail = p ? own(p, "node-actions") : null;
        return rail ? Array.prototype.slice.call(rail.children) : [];
    }

    function moreButtonOf(head) {
        var p = own(head, "node-controls");
        return p ? own(p, "node-more") : null;
    }

    // The state cluster, which stands in the row after the toolbar's place, outside
    // it (`node_controls`).
    function stateOf(head) {
        return own(head, "status-card__state") || own(head, "status-node__state");
    }

    // Where the head keeps its buttons, the look `head_buttons` (ADR-0029): right
    // after the name, `pointer`; on a line of their own beneath the row, `line`; at the
    // row's end, `name`; right after the name, the name a link, `pointer-name`.
    function headButtons() {
        return document.body.getAttribute("data-ls-head-buttons") || "pointer";
    }

    // Whether the pointer's click on an open head's name follows its link to the
    // node's page, ↗ being the keyboard's alone: under `name` and `pointer-name`.
    function nameOpensPage() {
        var look = headButtons();
        return look === "name" || look === "pointer-name";
    }

    // Whether a head's state cluster stands beneath the row on its own, by the
    // deployment's word — `card_status_line: below` gives every card's head that line.
    function belowByDefault(head) {
        return head.classList.contains("status-card__head")
            && document.body.getAttribute("data-ls-card-state") === "below";
    }

    var gapOf = null;

    // The toolbar's gap between its items, read once from the stylesheet.
    function toolbarGap(head) {
        if (gapOf === null) {
            var p = own(head, "node-controls");
            gapOf = p ? parseFloat(getComputedStyle(p).columnGap) || 0 : 0;
        }
        return gapOf;
    }

    // What each row was read as, by its node's path: the row as the server drew it —
    // its own class, its box's and its markup — the width it was read at, and what
    // was drawn from the reading. A refresh draws a row the server drew the same, at
    // the same width, from what was read of it, and reads only the rows that changed:
    // on a quiet refresh none (backlog #91 §7.4).
    var rows = new Map();
    // The rows this script has drawn. What it drew is in their markup, so such a row
    // is read again whenever it is asked for — a box a click opens, a resize, the
    // fonts — and never matched against a row as the server drew it.
    var drawnRows = new WeakSet();
    // The root's font size the rows were read in: their parts are sized in rem, so a
    // larger one changes what every row needs while its width may stay.
    var fontSeen = null;

    // What was read is forgotten, the toolbar's gap with it: a resize, the fonts, a
    // pointer turned coarse or fine, the root's font.
    function forgetRows() {
        rows = new Map();
        gapOf = null;
    }

    function rowKey(head) {
        return (head.classList.contains("status-card__head") ? "card " : "box ")
            + head.getAttribute("data-path");
    }

    function rowAsDrawn(head) {
        var box = head.parentElement;
        return head.className + "\n" + (box ? box.className : "") + "\n" + head.innerHTML;
    }

    // Every shown head at once, the grid planned first (`dashboard-layout.js`), so
    // that each row is read at the width its card is drawn at. A row the server drew
    // as it drew one read before, at that one's width, is drawn from that reading;
    // every other is set up to be read (`is-measuring`: the row with its title gone,
    // the name whole, every action and ⋯ shown, the state in the row unless the
    // deployment keeps it beneath), every such row is read in one layout — how far it
    // overflows, and the width of each action, of ⋯ and of the state — and from that
    // each head is drawn: the actions the row has no room for fold behind ⋯ from the
    // last, ⋯ standing only where something folds; where the name would still be
    // cut, or one action fold alone, the state drops to its own line beneath, which
    // gives the actions its room back; the name gives way last.
    function applyAllHeads(heads) {
        if (window.lsLayout) { window.lsLayout.apply(); }
        var font = getComputedStyle(document.documentElement).fontSize;
        if (font !== fontSeen) { forgetRows(); fontSeen = font; }
        var seen = [];
        var pending = [];
        var i, j, it;
        // Under the look `line` the buttons have a line of their own and the row wraps
        // its state beneath where it has no room for it, as a closed card's does, so
        // no row is read.
        var reads = headButtons() !== "line";
        for (i = 0; i < heads.length; i++) {
            var head = heads[i];
            if (!reads || !shown(head) || head.closest(".status-card.is-closed")) {
                head.classList.remove("is-state-below", "is-state-beside",
                                      "is-crowded");
                giveRoom(head, 0);
                continue;
            }
            it = { head: head, fresh: !drawnRows.has(head) };
            if (it.fresh) { it.key = rowKey(head); it.drawn = rowAsDrawn(head); }
            seen.push(it);
        }
        // every width in one layout, then each row drawn from what was read of it
        // where that holds, and set up to be read where it does not
        for (i = 0; i < seen.length; i++) {
            seen[i].width = seen[i].head.getBoundingClientRect().width;
        }
        for (i = 0; i < seen.length; i++) {
            it = seen[i];
            var was = it.fresh ? rows.get(it.key) : null;
            if (was && was.drawn === it.drawn && Math.abs(was.width - it.width) < 0.05) {
                drawRow(it.head, was.folded, was.below, was.crowded);
                it.head.classList.toggle("is-state-beside", was.beside);
                giveRoom(it.head, was.room);
            } else {
                it.head.classList.remove("is-state-below", "is-state-beside",
                                         "is-crowded");
                giveRoom(it.head, 0);
                it.head.classList.add("is-measuring");
                pending.push(it);
            }
            drawnRows.add(it.head);
        }
        for (i = 0; i < pending.length; i++) {
            it = pending[i];
            var h = it.head;
            it.excess = rowExcess(h);
            it.actions = actionsOf(h);
            it.widths = [];
            for (j = 0; j < it.actions.length; j++) {
                it.widths.push(it.actions[j].getBoundingClientRect().width);
            }
            var more = moreButtonOf(h);
            it.moreWidth = more ? more.getBoundingClientRect().width : 0;
            var state = stateOf(h);
            it.stateWidth = state && !belowByDefault(h) ? state.getBoundingClientRect().width : 0;
            it.gap = toolbarGap(h);
        }
        for (i = 0; i < pending.length; i++) {
            drawHead(pending[i]);
        }
        // Where the state is beneath, it is tried beside the name's last line — the
        // head without a line of its own for it, the toolbar at the row's top — and
        // keeps that place only where it touches neither the name nor the rest of
        // the toolbar: all tried, all read in one layout, the misses put back.
        var tried = [];
        for (i = 0; i < pending.length; i++) {
            var drawn = pending[i].head;
            if (drawn.classList.contains("is-state-below") || belowByDefault(drawn)) {
                drawn.classList.add("is-state-beside");
                tried.push(drawn);
            }
        }
        var misses = [];
        for (i = 0; i < tried.length; i++) {
            if (!clearBeside(tried[i])) { misses.push(tried[i]); }
        }
        for (i = 0; i < misses.length; i++) {
            misses[i].classList.remove("is-state-beside");
        }
        // A state at the head's foot that its line is too narrow for breaks between
        // its parts (`overview.css`), and the head makes room for every line it takes:
        // all read in one layout, then each head given its room.
        for (i = 0; i < pending.length; i++) {
            pending[i].room = roomNeeded(pending[i].head);
        }
        for (i = 0; i < pending.length; i++) {
            giveRoom(pending[i].head, pending[i].room);
        }
        // what each row as the server drew it was read as, for the next refresh
        for (i = 0; i < pending.length; i++) {
            it = pending[i];
            if (!it.fresh) { continue; }
            rows.set(it.key, { drawn: it.drawn, width: it.width, folded: it.folded,
                               crowded: it.crowded,
                               below: it.head.classList.contains("is-state-below"),
                               beside: it.head.classList.contains("is-state-beside"),
                               room: it.room });
        }
    }

    // The room a head keeps beneath its row for a state at its foot that breaks onto
    // more lines than the one the head keeps for it, in pixels: none where one line
    // holds it, or where the state stands in the row or beside the name.
    function roomNeeded(head) {
        var state = stateOf(head);
        if (!state || head.classList.contains("is-state-beside")
                || !(head.classList.contains("is-state-below") || belowByDefault(head))) {
            return 0;
        }
        var tall = state.getBoundingClientRect().height;
        var kept = parseFloat(getComputedStyle(head).paddingBottom) || 0;
        return tall > kept + 0.5 ? Math.ceil(tall) : 0;
    }

    function giveRoom(head, room) {
        if (room) { head.style.setProperty("--ls-state-room", room + "px"); }
        else { head.style.removeProperty("--ls-state-room"); }
    }

    // Whether a head's state, at its foot with no line of its own, stands clear of
    // the name's lines and of the rest of the toolbar — with the toolbar's gap kept
    // before it, so it never touches the end of the name.
    function clearBeside(head) {
        var state = stateOf(head);
        if (!state) { return false; }
        var s = state.getBoundingClientRect();
        var gap = toolbarGap(head);
        var left = s.left - gap;
        var hits = function (r) {
            return r.width > 0 && r.height > 0 && r.right > left && r.left < s.right
                && r.bottom > s.top && r.top < s.bottom;
        };
        var name = own(head, "status-card__name") || own(head, "status-node__name");
        if (name) {
            var range = document.createRange();
            range.selectNodeContents(name);
            var lines = range.getClientRects();
            // the state's place is the name's second line: a name of one line has none,
            // whatever room the row's end may have where the look keeps the toolbar
            // after the name
            var first = null;
            var broke = false;
            for (var i = 0; i < lines.length; i++) {
                if (hits(lines[i])) { return false; }
                if (!lines[i].width) { continue; }
                if (first === null) { first = lines[i].top; }
                else if (Math.abs(lines[i].top - first) > 1) { broke = true; }
            }
            if (!broke) { return false; }
        }
        // and of the toolbar's items
        var toolbar = own(head, "node-controls");
        var bar = toolbar ? toolbar.children : [];
        for (var j = 0; j < bar.length; j++) {
            if (hits(bar[j].getBoundingClientRect())) { return false; }
        }
        return true;
    }

    // How far a row's parts overrun the row, in fractional pixels: what its children
    // in the flow are wide with their margins, less what the row has inside its
    // padding. `scrollWidth` would say it in whole pixels, a few short.
    function rowExcess(head) {
        var need = 0;
        var kids = head.children;
        for (var i = 0; i < kids.length; i++) {
            var style = getComputedStyle(kids[i]);
            if (style.display === "none" || style.position === "absolute") { continue; }
            need += kids[i].getBoundingClientRect().width
                  + (parseFloat(style.marginLeft) || 0) + (parseFloat(style.marginRight) || 0);
        }
        var own = getComputedStyle(head);
        var have = head.getBoundingClientRect().width
                 - (parseFloat(own.paddingLeft) || 0) - (parseFloat(own.paddingRight) || 0);
        return need - have;
    }

    // How many actions fit, from the first, with `room` pixels to give back: each
    // folded action gives its width and the gap before it — the first action has
    // none, the rail's gaps being between its items — and ⋯ was in the row as read.
    function fitting(it, room) {
        var folded = 0;
        var left = room;
        while (left > 0 && folded < it.actions.length) {
            var index = it.actions.length - 1 - folded;
            left -= it.widths[index] + (index > 0 ? it.gap : 0);
            folded += 1;
        }
        return { folded: folded, left: left };
    }

    function drawHead(it) {
        // What the row must give back is its overflow as measured, ⋯ among the items,
        // so that where something folds, ⋯ has its square already. ⋯ stands only
        // where something folds, so an overflow its square and gap give back
        // (`spare`) folds nothing: the row fits once ⋯ is gone.
        var spare = it.moreWidth > 0 ? it.moreWidth + it.gap : 0;
        var excess = it.excess > 0 ? it.excess + SLACK_PX : it.excess;
        var below = false;
        var folded = 0;
        // Whether the name gives way, as the row still overruns with every action
        // folded and the state beneath: the toolbar keeps its room in the row there,
        // so that the name breaks beside it, where elsewhere it takes none under the
        // pointer's looks and lies over the title when shown (`overview.css`).
        var crowded = false;
        if (excess > spare) {
            var fit = fitting(it, excess);
            folded = fit.folded;
            crowded = fit.left > 0;
            if (it.stateWidth && (fit.left > 0 || folded === 1)) {
                // The state goes beneath, and the actions get its room back, where
                // not even every action folded leaves the name whole; and where one
                // action would fold alone, if its line keeps that action in the row —
                // ⋯ never holds a lone action the state's line makes room for. Where it
                // does not, the state keeps its place.
                var rest = excess - it.stateWidth - it.gap;
                var beneath = rest > spare ? fitting(it, rest) : null;
                if (fit.left > 0 || !beneath || beneath.folded === 0) {
                    below = true;
                    folded = beneath ? beneath.folded : 0;
                    crowded = beneath !== null && beneath.left > 0;
                }
            }
        }
        it.folded = folded;
        it.crowded = crowded;
        drawRow(it.head, folded, below, crowded);
        it.head.classList.remove("is-measuring");
    }

    // A row as read: its last `folded` actions behind ⋯, ⋯ shown where any are, the
    // state beneath where `below`, and the toolbar's room kept where the name gives
    // way, `crowded` — written only where it differs.
    function drawRow(head, folded, below, crowded) {
        var actions = actionsOf(head);
        for (var j = 0; j < actions.length; j++) {
            actions[j].classList.toggle("is-folded", j >= actions.length - folded);
        }
        var more = moreButtonOf(head);
        if (more) {
            if (folded > 0) { more.removeAttribute("hidden"); }
            else {
                if (!more.hasAttribute("hidden")) { more.setAttribute("hidden", ""); }
                closeMenu(more);
            }
        }
        head.classList.toggle("is-state-below", below);
        head.classList.toggle("is-crowded", !!crowded);
    }

    // The heads beneath a node's wrapper, its own first, shown or not.
    function headsBeneath(hold) {
        return hold.querySelectorAll(".status-node__self, .status-card__head");
    }

    // What is measured on open: a box hidden at the swap measures nothing, so its
    // lines' overflow, its head's ⋯ and its state's line are measured once it is
    // shown — and those of every open box beneath it.
    function measure(node) {
        var hold = holdOf(node);
        if (!hold) { return; }
        var heads = [];
        var head = headOf(node);
        if (head) { heads.push(head); }
        var beneath = headsBeneath(hold);
        for (var i = 0; i < beneath.length; i++) { heads.push(beneath[i]); }
        applyAllHeads(heads);
        applyAllLines(hold.querySelectorAll(".reason-block"));
        applyToolbars(heads);
    }

    // --- the toolbar's one stop ----------------------------------------------------------

    // Which control of a head's toolbar holds the tab stop, by node, for the page's
    // life: a control's `data-control`, or `action:N` for the N-th action.
    var stops = {};

    function keyOf(control) {
        var kind = control.getAttribute("data-control");
        if (kind) { return kind; }
        if (control.classList.contains("maintenance-pip")) { return "pip"; }
        var item = control.closest(".node-actions > *");
        var rail = item ? item.parentElement : null;
        if (!rail) { return null; }
        return "action:" + Array.prototype.indexOf.call(rail.children, item);
    }

    function controlFor(controls, key) {
        for (var i = 0; i < controls.length; i++) {
            if (keyOf(controls[i]) === key) { return controls[i]; }
        }
        return null;
    }

    // One tab stop per toolbar: the control kept for the node, else the first; the
    // rest `tabindex="-1"`. Written only where it differs, so a swap costs little.
    function applyToolbar(head) {
        var node = nodeOf(head);
        var controls = controlsOf(head);
        if (!controls.length) { return; }
        var stop = controlFor(controls, node ? stops[pathOf(node)] : null) || controls[0];
        for (var i = 0; i < controls.length; i++) {
            var want = controls[i] === stop ? "0" : "-1";
            if (controls[i].getAttribute("tabindex") !== want) {
                controls[i].setAttribute("tabindex", want);
            }
            // ‖ and the ringed check are links until the script makes them their
            // editors' controls: each says here that it opens one, which the server
            // leaves off every head
            var key = keyOf(controls[i]);
            if ((key === "pin" || key === "ack")
                    && !controls[i].hasAttribute("aria-expanded")) {
                controls[i].setAttribute("aria-expanded", "false");
            }
        }
    }

    function applyToolbars(heads) {
        for (var i = 0; i < heads.length; i++) {
            if (shown(heads[i])) { applyToolbar(heads[i]); }
        }
    }

    // Move the focus to `control`; the stop follows it (`focusin`, below).
    function focusOn(control) {
        try { control.focus({ preventScroll: true }); } catch (e) { control.focus(); }
    }

    grid.addEventListener("keydown", function (e) {
        if (!e.target.closest) { return; }
        var toolbar = e.target.closest(".node-controls");
        if (!toolbar || e.target.closest(".node-actions-menu")) { return; }
        var head = toolbar.parentElement;
        var controls = controlsOf(head);
        var at = controls.indexOf(e.target);
        if (at < 0) { return; }
        var to = -1;
        if (e.key === "ArrowRight") { to = Math.min(controls.length - 1, at + 1); }
        else if (e.key === "ArrowLeft") { to = Math.max(0, at - 1); }
        else if (e.key === "Home") { to = 0; }
        else if (e.key === "End") { to = controls.length - 1; }
        if (to < 0) { return; }
        e.preventDefault();
        focusOn(controls[to]);
    });

    // the stop follows a click or a Tab into the toolbar, so Shift+Tab comes back to it
    grid.addEventListener("focusin", function (e) {
        if (!e.target.closest) { return; }
        var toolbar = e.target.closest(".node-controls");
        if (!toolbar || e.target.closest(".node-actions-menu")) { return; }
        var head = toolbar.parentElement;
        if (controlsOf(head).indexOf(e.target) < 0) { return; }
        var node = nodeOf(head);
        var key = keyOf(e.target);
        if (node && key && stops[pathOf(node)] !== key) {
            stops[pathOf(node)] = key;
            applyToolbar(head);
        }
    });

    // --- ⋯: the actions the row had no room for --------------------------------------------

    // A change this script makes to the grid's elements is not a swap: the observer
    // that watches for one is kept from seeing it (its records go with `disconnect`).
    function quietly(change) {
        if (observer) { observer.disconnect(); }
        try { return change(); }
        finally { if (observer) { observer.observe(grid, { childList: true, subtree: true }); } }
    }

    var openMenu = null;

    function closeMenu(button) {
        var menu = openMenu;
        if (!menu || (button && menu.button !== button)) { return; }
        quietly(function () { menu.list.remove(); });
        menu.button.setAttribute("aria-expanded", "false");
        openMenu = null;
    }

    // A menu beneath ⋯ of the folded actions, each a copy of its action with its
    // label shown; the originals stay where they are, hidden, so a swap draws them
    // again and the menu is built afresh from them.
    function showMenu(button) {
        if (openMenu && openMenu.button === button) { closeMenu(button); return; }
        closeMenu();
        var head = button.closest(".status-node__self, .status-card__head");
        var list = document.createElement("ul");
        list.className = "node-actions-menu";
        list.setAttribute("role", "menu");
        var folded = actionsOf(head).filter(function (item) {
            return item.classList.contains("is-folded");
        });
        folded.forEach(function (item) {
            var copy = item.cloneNode(true);
            copy.classList.remove("is-folded");
            var control = copy.matches("a, button") ? copy : copy.querySelector("a, button");
            if (control) {
                control.setAttribute("role", "menuitem");
                control.setAttribute("tabindex", "-1");
                if (control.classList.contains("is-icon")) {
                    control.appendChild(document.createTextNode(
                        control.getAttribute("aria-label") || control.getAttribute("title") || ""));
                }
            }
            var li = document.createElement("li");
            li.setAttribute("role", "none");
            li.appendChild(copy);
            list.appendChild(li);
        });
        // after the toolbar, in the head, beneath whose row it opens
        quietly(function () { head.appendChild(list); });
        button.setAttribute("aria-expanded", "true");
        openMenu = { button: button, list: list };
        var first = list.querySelector("[role=\"menuitem\"]");
        if (first) { try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); } }
    }

    grid.addEventListener("keydown", function (e) {
        if (!openMenu || !e.target.closest) { return; }
        var inMenu = e.target.closest(".node-actions-menu");
        if (e.key === "Escape") {
            var button = openMenu.button;
            closeMenu();
            e.preventDefault();
            try { button.focus({ preventScroll: true }); } catch (err) { button.focus(); }
            return;
        }
        if (!inMenu) { return; }
        var items = Array.prototype.slice.call(inMenu.querySelectorAll("[role=\"menuitem\"]"));
        var at = items.indexOf(e.target);
        var to = -1;
        if (e.key === "ArrowDown") { to = (at + 1) % items.length; }
        else if (e.key === "ArrowUp") { to = (at - 1 + items.length) % items.length; }
        else if (e.key === "Home") { to = 0; }
        else if (e.key === "End") { to = items.length - 1; }
        if (to < 0 || !items.length) { return; }
        e.preventDefault();
        items[to].focus();
    });

    // a click anywhere else, or a swap, closes the menu
    document.addEventListener("pointerdown", function (e) {
        if (!openMenu || !e.target.closest) { return; }
        if (e.target.closest(".node-actions-menu") || e.target === openMenu.button
                || openMenu.button.contains(e.target)) { return; }
        closeMenu();
    }, true);

    // --- ‖ and the ringed check: the page's one editor of each, cloned into the box ----

    // The open clone, if any: one at a time, as a line's editors are — ‖'s or the
    // ringed check's.
    function pinClone() {
        return grid.querySelector("details.pin-setter.is-clone, details.ack-setter.is-clone");
    }

    function removeClone(clone, refocus) {
        var node = nodeOf(clone);
        var kind = clone.classList.contains("ack-setter") ? "ack" : "pin";
        quietly(function () { clone.remove(); });
        if (!node) { return; }
        var button = iconOf(node, kind);
        if (button) {
            button.setAttribute("aria-expanded", "false");
            if (refocus) { try { button.focus({ preventScroll: true }); } catch (e) { button.focus(); } }
        }
    }

    // What a ringed check marks, in its editor's words: the one failure at or
    // beneath the node, or how many, each its own (ADR-0142).
    function marked(button, name) {
        var count = parseInt(button.getAttribute("data-ack-count") || "1", 10);
        return count === 1 ? "the one failure at " + name
                           : "the " + count + " failures at and beneath " + name
                             + ", each its own";
    }

    // Clone the page's editor into the node's box, where the block will stand — a
    // card's panel's start, a box after its head's row — with the node's path and
    // what it would cover filled in, and open it; the open editor holds the refresh
    // (poll.js), and Cancel or Escape close it (maintenance-edit.js), which takes the
    // clone away again (the `toggle` below). ‖'s says what the pin would cover; the
    // ringed check's what it marks seen, and carries the digest of those failures,
    // which the write compares with what fails there then.
    function openPin(node, button, kind) {
        var ack = kind === "ack";
        var template = document.getElementById(ack ? "ack-editor" : "pin-editor");
        if (!template || !template.content) { return false; }
        var standing = pinClone();
        if (standing) {
            var same = nodeOf(standing) === node
                && standing.classList.contains("ack-setter") === ack;
            removeClone(standing, false);
            if (same) { return true; }
        }
        var clone = template.content.firstElementChild.cloneNode(true);
        clone.classList.add("is-clone");
        var path = pathOf(node);
        var field = clone.querySelector("input[name=\"path\"]");
        if (field) { field.value = path; }
        var toggle = toggleOf(node);
        var name = toggle ? toggle.textContent.trim() : path;
        if (ack) {
            var parts = clone.querySelector("input[name=\"parts\"]");
            if (parts) { parts.value = button.getAttribute("data-ack-parts") || ""; }
            var marks = clone.querySelector(".ack-editor__what");
            if (marks) { marks.textContent = marked(button, name); }
        } else {
            var what = clone.querySelector(".pin-editor__what");
            if (what) {
                what.textContent = name + (button.hasAttribute("data-beneath")
                                           ? " and everything beneath it" : "");
            }
        }
        var p = partsOf(node);
        if (!p.box) { return false; }
        quietly(function () {
            if (p.card) { p.box.insertBefore(clone, p.box.firstChild); }
            else { p.box.insertBefore(clone, p.head.nextSibling); }
        });
        button.setAttribute("aria-expanded", "true");
        clone.open = true;
        return true;
    }

    // `toggle` does not bubble, hence the capture: a clone closed by Cancel, Escape
    // or its summary goes, and the focus comes back to ‖.
    grid.addEventListener("toggle", function (e) {
        var clone = e.target;
        if (!clone.classList) { return; }
        if (clone.classList.contains("is-in-row")) { setterToggled(clone); return; }
        if (!clone.classList.contains("is-clone") || clone.open) { return; }
        removeClone(clone, true);
    }, true);

    // --- ‖ on a page's own head: the editor the head keeps -------------------------------

    // A node's page keeps an editor of its own for the node's pin, beneath its head's
    // row where the block will stand, so a pin is set there without script (backlog
    // #91 §3.7): its *Set maintenance* is the browser's disclosure. With script the
    // head's ‖ opens it, as ‖ opens an editor on every head, and the disclosure is
    // kept out of sight while it is closed (`.is-in-row`).
    // The head's own editor of a kind: ‖'s *Set maintenance*, or the ringed check's
    // *Mark seen* (ADR-0142).
    function setterOf(node, kind) {
        var lead = partsOf(node).lead;
        return lead ? own(lead, kind === "ack" ? "ack-setter" : "rule-setter") : null;
    }

    function drawSetter(node) {
        ["pin", "ack"].forEach(function (kind) {
            var button = iconOf(node, kind);
            var setter = setterOf(node, kind);
            if (!button || !setter) { return; }
            setter.classList.add("is-in-row");
            button.removeAttribute("hidden");
            button.setAttribute("aria-expanded", setter.open ? "true" : "false");
        });
    }

    function setterToggled(setter) {
        var node = nodeOf(setter);
        var button = node ? iconOf(node, setter.classList.contains("ack-setter")
                                         ? "ack" : "pin") : null;
        if (!button) { return; }
        button.setAttribute("aria-expanded", setter.open ? "true" : "false");
        // closed by Cancel or Escape, whose own focus went to a summary out of sight
        var active = document.activeElement;
        if (!setter.open && (!active || active === document.body || setter.contains(active))) {
            try { button.focus({ preventScroll: true }); } catch (err) { button.focus(); }
        }
    }

    // --- a swap poll.js did not make: the heads measured again ----------------------------

    var resizeTimer = null;

    function measureAll() {
        if (observer) { observer.disconnect(); }
        parts = new Map();
        forgetRows();
        var heads = grid.querySelectorAll(".status-node__self, .status-card__head");
        applyAllHeads(heads);
        applyAllLines(grid.querySelectorAll(".reason-block"));
        applyToolbars(heads);
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    function resized() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(measureAll, RESIZE_MS);
    }

    // the grid's width is what the rows have: watched where the browser can, as
    // dashboard-layout.js watches it, and the window's resize otherwise
    if (window.ResizeObserver) {
        var widthSeen = grid.getBoundingClientRect().width;
        new ResizeObserver(function () {
            var width = grid.getBoundingClientRect().width;
            if (width === widthSeen) { return; }
            widthSeen = width;
            resized();
        }).observe(grid);
    } else {
        window.addEventListener("resize", resized);
    }

    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function () {
            widths = new Map();
            applyWidths(grid);
            measureAll();
        }, function () { /* no fonts */ });
    }

    // A pointer turned coarse or fine — a touch screen taken up or put down — spaces
    // the toolbars otherwise, while no width moves: every head measured again at once.
    var coarse = window.matchMedia ? window.matchMedia("(pointer: coarse)") : null;
    if (coarse && coarse.addEventListener) {
        coarse.addEventListener("change", function () { measureAll(); });
    } else if (coarse && coarse.addListener) {
        coarse.addListener(function () { measureAll(); });
    }

    // --- a close holds for its incident (decision 9) -----------------------------------

    function incidents(root) {
        var stamp = root.querySelector("[data-rendered-s]")
                 || grid.querySelector("[data-rendered-s]");
        var now = stamp ? Number(stamp.getAttribute("data-rendered-s")) : NaN;
        if (!isFinite(now)) { return; }
        var changed = false;
        for (var path in map.nodes) {
            var entry = map.nodes[path];
            if (entry.open !== false) { continue; }
            var node = root.querySelector(".tree-node[data-node=" + quoted(path) + "]");
            if (!node) { continue; }
            if (node.hasAttribute("data-failing")) {
                if (entry.ok_held) {
                    // the incident ended and a new one began: the close gives way
                    delete entry.open; delete entry.ok_since; delete entry.ok_held;
                    if (!Object.keys(entry).length) { delete map.nodes[path]; }
                } else if (entry.ok_since !== undefined) {
                    delete entry.ok_since;              // a flicker: the count restarts
                }
                changed = true;
            } else if (entry.ok_since === undefined) {
                entry.ok_since = now; changed = true;
            } else if (!entry.ok_held && now - entry.ok_since >= INCIDENT_S) {
                entry.ok_held = true; changed = true;
            }
        }
        if (changed) { write(); }
    }

    // --- the band's three buttons (decision 7) -----------------------------------------

    var modes = document.querySelector(".ls-band__modes");

    function hasDepth() {
        try { return new URLSearchParams(window.location.search).has("depth"); }
        catch (e) { return false; }
    }

    function drawBand() {
        if (!modes) { return; }
        modes.removeAttribute("hidden");
        var count = Object.keys(map.nodes).length + (hasDepth() ? 1 : 0);
        var inForce = map.mode === null ? "configured" : map.mode;
        var buttons = modes.querySelectorAll("[data-mode]");
        for (var i = 0; i < buttons.length; i++) {
            var button = buttons[i];
            var pressed = button.getAttribute("data-mode") === inForce;
            button.setAttribute("aria-pressed", pressed ? "true" : "false");
            var tally = button.querySelector(".ls-band__count");
            if (tally) {
                if (pressed && count) {
                    tally.textContent = "\u00B7 " + count;
                    tally.removeAttribute("hidden");
                } else {
                    tally.textContent = "";
                    tally.setAttribute("hidden", "");
                }
            }
        }
    }

    function setMode(mode) {
        var inForce = map.mode === null ? "configured" : map.mode;
        if (mode === inForce) {
            // a click on the button in force drops what it counts, and keeps the mode
            map.nodes = {};
        } else if (mode === "configured") {
            map = empty();
        } else if (mode === "closed") {
            map.mode = "closed";
            for (var path in map.nodes) {
                var entry = map.nodes[path];
                if (entry.open === true) { map.nodes[path] = { open: true }; }
                else { delete map.nodes[path]; }
            }
        } else if (mode === "open") {
            map.mode = "open";
            for (var key in map.nodes) {
                var kept = map.nodes[key];
                delete kept.open; delete kept.ok_since; delete kept.ok_held;
                delete kept.chips; delete kept.ok;
                if (!Object.keys(kept).length) { delete map.nodes[key]; }
            }
        }
        write();
        if (mode === "configured" && hasDepth()) { withoutDepth(); return; }
        applyAll(grid);
    }

    // *As configured* under a `depth=`: the server drew that level closed, so the
    // address is loaded without it.
    function withoutDepth() {
        var url = new URL(window.location.href);
        url.searchParams.delete("depth");
        window.location.assign(url.toString());
    }

    if (modes) {
        modes.addEventListener("click", function (e) {
            var button = e.target.closest ? e.target.closest("[data-mode]") : null;
            if (!button) { return; }
            setMode(button.getAttribute("data-mode"));
        });
    }

    // --- apply ------------------------------------------------------------------------

    var observer = null;
    var swapping = false;

    // --- the runs' width (ADR-0127 decision 12) ---------------------------------------
    //
    // Under `chip_runs: aligned` a level's runs share one column width, `--chip-w` on
    // its `.tree-kids`: the server's estimate in characters, and here what its names
    // measure in the chip's own font — every child's, open or closed, whatever face
    // its node shows — the widest at most NAME_BOUND times their 90th percentile,
    // with what a chip adds to its name, its padding, its edge and its cue, and room
    // for the largest count of leaves among the level's branches (`data-leaves`), a
    // leaf bringing none. A level's width is kept by what it was measured from, so a
    // click, a status and a refresh leave it as it is and a reload in another state
    // draws the same columns; only another set of children measures it again, and so
    // do the fonts settling and the root's font size, which every chip is sized in.
    var widths = new Map();
    var widthFont = null;
    var ruler = null;

    function textWidth(text, font) {
        if (ruler === null) {
            try { ruler = document.createElement("canvas").getContext("2d"); } catch (e) { ruler = false; }
        }
        if (!ruler) { return 0; }
        ruler.font = font;
        return ruler.measureText(text).width;
    }

    function fontOf(style, weight) {
        return style.fontStyle + " " + (weight || style.fontWeight) + " "
            + style.fontSize + " " + style.fontFamily;
    }

    function px(value) { return parseFloat(value) || 0; }

    function chipsOfLevel(level) {
        return level.querySelectorAll(":scope > .tree-node > .tree-chip, "
            + ":scope > .tree-run > .tree-node > .tree-chip, "
            + ":scope > .tree-solo > .tree-node > .tree-chip");
    }

    function chipName(chip) {
        var name = chip.querySelector(".tree-chip__name");
        return name ? name.textContent || "" : "";
    }

    function measureLevel(level, chips) {
        if (!chips.length) { return 0; }
        var chip = chips[0];
        var style = getComputedStyle(chip);
        var nameEl = chip.querySelector(".tree-chip__name");
        var nameFont = fontOf(nameEl ? getComputedStyle(nameEl) : style);
        var names = [];
        for (var i = 0; i < chips.length; i++) {
            names.push(textWidth(chipName(chips[i]), nameFont));
        }
        names.sort(function (a, b) { return a - b; });
        var typical = names[Math.max(0, Math.ceil(0.9 * names.length) - 1)];
        var widest = Math.min(names[names.length - 1], NAME_BOUND * typical);
        var cue = chip.querySelector(":scope > .status-cue");
        var cueStyle = cue ? getComputedStyle(cue) : null;
        var width = px(style.paddingLeft) + px(style.paddingRight)
            + px(style.borderLeftWidth) + px(style.borderRightWidth)
            + (cueStyle ? px(cueStyle.width) + px(cueStyle.marginRight) : 0)
            + widest;
        var leaves = parseInt(level.getAttribute("data-leaves"), 10) || 0;
        var counts = leaves > 0 ? level.querySelector(".tree-chip > .tree-counts") : null;
        if (counts) {
            // the widest digits, in the bold a failing chip draws its counts in, after
            // the counts' own margin; a branch always draws its count
            var digits = new Array(String(leaves).length + 1).join("9");
            width += px(getComputedStyle(counts).marginLeft)
                + textWidth(digits, fontOf(style, "600"));
        }
        return Math.ceil(width) + 1;
    }

    function applyWidths(root) {
        if (!ALIGNED) { return; }
        var font = getComputedStyle(document.documentElement).fontSize;
        if (font !== widthFont) { widths = new Map(); widthFont = font; }
        var levels = root.querySelectorAll(".tree-kids[data-leaves]");
        for (var i = 0; i < levels.length; i++) {
            var level = levels[i];
            var chips = chipsOfLevel(level);
            var key = level.getAttribute("data-leaves");
            for (var j = 0; j < chips.length; j++) { key += "\n" + chipName(chips[j]); }
            var width = widths.get(key);
            if (width === undefined) {
                width = measureLevel(level, chips);
                widths.set(key, width);
            }
            if (width > 0) { level.style.setProperty("--chip-w", width + "px"); }
        }
    }

    // Every node's face from the markers and the map, parents before children (the
    // document's order), then each level's runs, then the heads' buttons, the folds,
    // the heads' rows and the boxes' lines — the last two measured once the boxes are
    // shown — and each toolbar's stop.
    function applyAll(root, pivot) {
        if (observer) { observer.disconnect(); }
        parts = new Map();
        closeMenu();
        incidents(root);
        var nodes = root.querySelectorAll(".tree-node");
        var i;
        for (i = 0; i < nodes.length; i++) {
            var look = lookOf(nodes[i]);
            showFace(nodes[i], look.open, look.why);
        }
        var levels = root.querySelectorAll(".tree-kids");
        for (i = 0; i < levels.length; i++) { reform(levels[i], pivot || null); }
        applyWidths(root);
        for (i = 0; i < nodes.length; i++) {
            drawChips(nodes[i]);
            drawFold(nodes[i]);
            if (isPageRoot(nodes[i])) { drawSetter(nodes[i]); }
        }
        var heads = root.querySelectorAll(".status-node__self, .status-card__head");
        applyAllHeads(heads);
        applyAllLines(root.querySelectorAll(".reason-block"));
        applyToolbars(heads);
        drawBand();
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    // One node and what its toggle touches: its face, its level's runs, its parent's
    // ▤ and fold, and its lines' overflow once it is shown.
    function applyNode(node, pivot) {
        if (observer) { observer.disconnect(); }
        parts = new Map();
        var look = lookOf(node);
        showFace(node, look.open, look.why);
        var level = levelOf(node);
        if (level) { reform(level, pivot || null); }
        var parent = parentOf(node);
        if (parent) { drawChips(parent); drawFold(parent); }
        drawChips(node);
        drawFold(node);
        if (look.open) { measure(node); }
        drawBand();
        packed();
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
        return look.open;
    }

    // --- the keyboard's focus ----------------------------------------------------------

    var kept = null;

    // The control the focus is on, and the node it belongs to: its `[data-path]`; a
    // node's action, which has no `data-control`, by its place in the rail.
    function noteFocus(root) {
        kept = null;
        var active = document.activeElement;
        if (!active || !root.contains(active) || !active.closest) { return; }
        // a chip is its node's toggle, as the head's name is
        var control = active.closest("[data-control], .tree-chip, .node-actions > *");
        if (!control) { return; }
        var kind = control.getAttribute("data-control")
            || (control.classList.contains("tree-chip") ? "toggle" : keyOf(active) || "toggle");
        var owner = control.closest("[data-path], .tree-node");
        if (!owner) { return; }
        kept = { kind: kind, path: owner.getAttribute(
            owner.hasAttribute("data-path") ? "data-path" : "data-node") };
    }

    function sameControl(root, want) {
        var node = root.querySelector(".tree-node[data-node=" + quoted(want.path) + "]");
        if (!node) {
            var row = root.querySelector("[data-path=" + quoted(want.path) + "]");
            return row ? row.querySelector("[data-control=" + quoted(want.kind) + "]") : null;
        }
        // the face that is shown holds the control: a chip has none but itself
        if (!isOpen(node)) { return want.kind === "toggle" ? chipOf(node) : null; }
        var head = headOf(node);
        var control = null;
        if (want.kind === "lines") {
            // *⌄ all N* stands after the node's block, and hidden takes no focus
            var box = partsOf(node).box;
            var block = box ? own(box, "reason-block") : null;
            var button = block ? moreOf(block) : null;
            return button && !button.hasAttribute("hidden") ? button : null;
        }
        if (want.kind.indexOf("action:") === 0 || want.kind === "pip") {
            return head ? controlFor(controlsOf(head), want.kind) : null;
        }
        control = head ? head.querySelector("[data-control=" + quoted(want.kind) + "]") : null;
        if (!control && want.kind === "ok-fold") {
            var mark = partsOf(node).mark;
            control = mark && !mark.hasAttribute("hidden") ? mark : null;
        }
        return control;
    }

    function restoreFocus(root) {
        var want = kept;
        kept = null;
        if (!want) { return; }
        var again = sameControl(root, want);
        if (!again) { return; }
        // without scrolling: putting the focus back never moves the wall
        try { again.focus({ preventScroll: true }); } catch (e) { again.focus(); }
    }

    function focusFace(node) {
        var target = isOpen(node) ? toggleOf(node) : (chipOf(node) || toggleOf(node));
        if (!target) { return; }
        try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); }
    }

    // --- where the window stands -------------------------------------------------------
    //
    // A swap replaces every element the browser's own scroll anchoring holds on to, and
    // the layouts in between — the map put back on the server's look, the grid planned —
    // move what it holds on to next, so a wall scrolled down stood hundreds of pixels
    // higher after a refresh. So `before` notes the nodes the window shows nearest its
    // top, above it or below, and where each stood, and `apply` scrolls by what the
    // nearest of them still shown moved once the new markup is laid out: the window shows
    // what it showed, a line added above it or not. A window at the page's top stays
    // there, whatever comes to stand at the head of the wall.
    var STOOD = 4;
    var stood = [];

    function noteWhere(root) {
        stood = [];
        if (window.scrollY <= 0) { return; }
        var nodes = root.querySelectorAll(".tree-node[data-node]");
        var reach = window.innerHeight;
        for (var i = 0; i < nodes.length; i++) {
            var box = nodes[i].getBoundingClientRect();
            if (!box.height || box.bottom <= 0 || box.top >= reach) { continue; }
            stood.push({ path: nodes[i].getAttribute("data-node"), top: box.top });
        }
        stood.sort(function (a, b) { return Math.abs(a.top) - Math.abs(b.top); });
        stood.length = Math.min(stood.length, STOOD);
    }

    function restoreWhere(root) {
        var was = stood;
        stood = [];
        for (var i = 0; i < was.length; i++) {
            var node = root.querySelector(".tree-node[data-node=" + quoted(was[i].path) + "]");
            var box = node ? node.getBoundingClientRect() : null;
            if (!box || !box.height) { continue; }
            var by = box.top - was[i].top;
            if (Math.abs(by) < 0.5) { return; }
            // at once, whatever the page's `scroll-behavior` says: a refresh never glides
            var html = document.documentElement;
            var behavior = html.style.scrollBehavior;
            html.style.scrollBehavior = "auto";
            window.scrollBy(0, by);
            html.style.scrollBehavior = behavior;
            return;
        }
    }

    // --- around each swap ------------------------------------------------------------

    function before(container) {
        swapping = true;
        closeMenu();
        noteFocus(container || grid);
        noteWhere(container || grid);
    }

    // Under the look `boxes: packed` the boxes take their columns once their heads are
    // drawn, before the window is put back where it stood (`dashboard-layout.js`,
    // ADR-0138): anew when the page is drawn, and in the columns they stand in after a
    // refresh or a click.
    function packed(drawn) {
        var layout = window.lsLayout;
        if (!layout || !layout.pack) { return; }
        if (drawn && layout.draw) { layout.draw(); } else { layout.pack(); }
    }

    // `drawn` on a load, which packs the boxes anew; a swap keeps their columns.
    function apply(container, drawn) {
        var root = container || grid;
        applyAll(root);
        packed(drawn);
        restoreFocus(root);
        restoreWhere(root);
        swapping = false;
        document.documentElement.classList.remove(PENDING);
        document.documentElement.classList.add(READY, DRAWN);
    }

    window.lsTree = { before: before, apply: apply };

    // --- toggling ---------------------------------------------------------------------

    // Open or close a node by the viewer's word: its entry is written where that
    // differs from how the view draws the node on its own, and removed where it
    // brings the node back to that. A close starts its incident's count afresh.
    function setOpen(node, open, pivot) {
        var path = pathOf(node);
        var own = lookOf(node, false).open;
        var entry = map.nodes[path] || {};
        delete entry.ok_since; delete entry.ok_held;
        if (open === own) { delete entry.open; } else { entry.open = open; }
        if (Object.keys(entry).length) { map.nodes[path] = entry; } else { delete map.nodes[path]; }
        write();
        return applyNode(node, pivot);
    }

    function toggle(node) {
        var open = setOpen(node, !isOpen(node));
        if (open) {
            var hold = holdOf(node);
            if (hold && hold.scrollIntoView) {
                try { hold.scrollIntoView({ block: "nearest" }); } catch (e) { /* older engines */ }
            }
        }
        focusFace(node);
    }

    // ▤: pressed opens every child; released or mixed folds every child to a chip.
    // Pressing it sets every child: the children's entries go, and one whose own
    // look would not follow gets an entry of its own (decision 5). A fold gives every
    // failing child one too, whatever this view draws it as: another of the tab's
    // views may open it by its own failure budget — the wall, where a node's page's
    // cards stand inside one card and share its three — and its close holds for its
    // incident there as here (§3.8).
    function pressChips(node) {
        var button = iconOf(node, "chips");
        var wantClosed = button.getAttribute("aria-pressed") !== "true";
        var path = pathOf(node);
        var entry = map.nodes[path] || {};
        var drawn = drawnChips(node);
        if ((wantClosed ? "true" : "false") === drawn) { delete entry.chips; }
        else { entry.chips = wantClosed; }
        if (Object.keys(entry).length) { map.nodes[path] = entry; } else { delete map.nodes[path]; }
        var level = kidsOf(node);
        var kids = level ? childrenOf(level) : [];
        for (var i = 0; i < kids.length; i++) {
            var kid = map.nodes[pathOf(kids[i])] || {};
            delete kid.open; delete kid.ok_since; delete kid.ok_held;
            if (Object.keys(kid).length) { map.nodes[pathOf(kids[i])] = kid; }
            else { delete map.nodes[pathOf(kids[i])]; }
            if (lookOf(kids[i]).open === wantClosed
                    || (wantClosed && kids[i].hasAttribute("data-failing"))) {
                kid = map.nodes[pathOf(kids[i])] || {};
                kid.open = !wantClosed;
                map.nodes[pathOf(kids[i])] = kid;
            }
        }
        write();
        if (observer) { observer.disconnect(); }
        parts = new Map();
        for (var j = 0; j < kids.length; j++) {
            var look = lookOf(kids[j]);
            showFace(kids[j], look.open, look.why);
        }
        if (level) { reform(level, null); }
        for (var k = 0; k < kids.length; k++) {
            drawChips(kids[k]); drawFold(kids[k]);
            if (isOpen(kids[k])) { measure(kids[k]); }
        }
        drawChips(node);
        drawFold(node);
        drawBand();
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    // The funnel: a fold the viewer presses takes the `show_when_quiet` claims too, so
    // its entry stays wherever a claim stands beneath or on the node, even where the
    // configuration folds as well.
    function pressFold(node) {
        var fold = foldOf(node);
        var want = !fold.folded;
        var path = pathOf(node);
        var entry = map.nodes[path] || {};
        var drawn = map.mode === "open" ? false : node.getAttribute("data-ok") === "true";
        var claims = node.hasAttribute("data-swq")
                  || !!(kidsOf(node) && kidsOf(node).querySelector(":scope > .tree-node[data-swq], :scope > .tree-run > .tree-node[data-swq]"));
        if (want === drawn && !(want && claims)) { delete entry.ok; } else { entry.ok = want; }
        if (Object.keys(entry).length) { map.nodes[path] = entry; } else { delete map.nodes[path]; }
        write();
        if (observer) { observer.disconnect(); }
        parts = new Map();
        drawFold(node);
        drawBand();
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    // --- clicks -----------------------------------------------------------------------

    var pressedAt = null;

    grid.addEventListener("pointerdown", function (e) {
        pressedAt = { x: e.clientX, y: e.clientY };
        endReveal();
    }, true);

    function dragged(e) {
        if (!pressedAt) { return false; }
        return Math.abs(e.clientX - pressedAt.x) > DRAG_PX
            || Math.abs(e.clientY - pressedAt.y) > DRAG_PX;
    }

    grid.addEventListener("click", function (e) {
        if (!e.target.closest) { return; }
        var lines = e.target.closest(".reason-more");
        if (lines) {
            e.preventDefault();
            e.stopPropagation();
            var block = blockOf(lines);
            if (!block) { return; }
            var path = block.getAttribute("data-reason-node");
            hold(path, "lines", held(path, "lines") ? undefined : true);
            applyLines(block);
            return;
        }
        if (e.target.closest(".node-actions-menu")) {
            // an action's own meaning, and the menu's job is done
            closeMenu();
            return;
        }
        var moreActions = e.target.closest(".node-more");
        if (moreActions) {
            e.preventDefault();
            e.stopPropagation();
            showMenu(moreActions);
            return;
        }
        var icon = e.target.closest(".node-icons > [data-control]");
        if (icon) {
            var kind = icon.getAttribute("data-control");
            if (kind === "page") { return; }                 // the link's own meaning
            var owner = nodeOf(icon);
            if (!owner) { return; }
            if ((kind === "pin" || kind === "ack") && isPageRoot(owner)) {
                // a page's own head opens the editor it keeps
                var setter = setterOf(owner, kind);
                if (!setter) { return; }
                e.preventDefault();
                e.stopPropagation();
                setter.open = !setter.open;
                return;
            }
            if (kind === "pin" || kind === "ack") {
                // a click with a modifier, and a middle click, keep the link's own
                // meaning; without the page's editor the link is followed
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) { return; }
                if (!openPin(owner, icon, kind)) { return; }
                e.preventDefault();
                e.stopPropagation();
                return;
            }
            e.preventDefault();
            e.stopPropagation();
            if (kind === "chips") { pressChips(owner); }
            else if (kind === "ok") { pressFold(owner); }
            return;
        }
        var mark = e.target.closest(".tree-ok");
        if (mark) {
            e.preventDefault();
            e.stopPropagation();
            var folded = nodeOf(mark);
            if (folded) { pressFold(folded); }
            return;
        }
        // a chip, or anywhere on an open node's head row but its own controls
        var chip = e.target.closest(".tree-chip");
        var row = chip ? null : e.target.closest(".status-node__self, .status-card__head");
        var node = nodeOf(chip || row);
        if (!node) { return; }
        if (!chip && (e.target.closest(OWN_CONTROLS) || row !== headOf(node))) { return; }
        // nothing closes the node its page is about
        if (isPageRoot(node)) { return; }
        // a click with a modifier, and a middle click, keep the link's own meaning
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) { return; }
        if (chip && chip.hasAttribute("hidden")) { return; }
        // under the looks `name` and `pointer-name` the pointer's click on an open
        // head's name follows its link to the node's page; the keyboard's Enter, a
        // click with no pointer (`detail` 0), opens and closes the node as Space does
        // (ADR-0029)
        if (!chip && e.detail !== 0 && nameOpensPage()
                && e.target.closest(".status-card__name, .status-node__name")
                && !node.classList.contains("is-closed")) { return; }
        // a click that ends a drag — the pointer travelled, selecting the head's text
        // — keeps the selection; the keyboard's click (Enter) has no pointer and is
        // never one (a drag that starts on the name, a link, is the browser's own
        // drag of the link and ends in no click at all)
        if (!chip && e.detail !== 0 && dragged(e)) { return; }
        pressedAt = null;
        e.preventDefault();
        toggle(node);
    });

    // Enter follows the link, which the click above takes; Space has no meaning on a
    // link and gets the toggle's.
    grid.addEventListener("keydown", function (e) {
        if (e.key !== " " && e.key !== "Spacebar") { return; }
        if (!e.target.closest) { return; }
        var control = e.target.closest(".tree-chip, [data-control=\"toggle\"]");
        if (!control || e.target !== control) { return; }
        var node = nodeOf(control);
        if (!node) { return; }
        e.preventDefault();
        toggle(node);
    });

    // --- a find (decision 11) ----------------------------------------------------------

    // The browser fires `beforematch` at each closed `.tree-hold` above what its find
    // (or a fragment in the address) matched, the innermost first, before it shows
    // them and scrolls to the match. Each is opened as a click would, its level
    // re-formed around the node and never the node itself, so the match stays where
    // the browser found it. The reveal is provisional for two seconds: what it opened
    // closes again when the first `beforematch` of a later reveal comes outside it
    // within them, but for the nodes above the new match.
    var reveal = null;

    function endReveal() { reveal = null; }

    grid.addEventListener("beforematch", function (e) {
        var hold = e.target;
        if (!hold.classList || !hold.classList.contains("tree-hold")) { return; }
        var node = hold.parentElement;
        if (!node || !node.classList.contains("tree-node")) { return; }
        var path = pathOf(node);
        var now = Date.now();
        if (reveal && now - reveal.at <= REVEAL_MS && !related(path, reveal.paths)) {
            undo(reveal, path);
            reveal = null;
        }
        if (!reveal || now - reveal.at > REVEAL_MS) {
            reveal = { at: now, paths: [], before: {} };
        }
        if (reveal.paths.indexOf(path) < 0) {
            reveal.paths.push(path);
            reveal.before[path] = map.nodes[path] ? JSON.parse(JSON.stringify(map.nodes[path]))
                                                  : null;
        }
        revealing = hold;
        try { setOpen(node, true, node); } finally { revealing = null; }
        // the box is shown once the browser has taken the attribute off: measured then
        setTimeout(function () { measure(node); }, 0);
    });

    // Whether `path` belongs to the reveal `paths` are of: one of them, beneath one
    // — the browser fires at the innermost first, then at each ancestor — or above
    // one. A match elsewhere is a reveal of its own.
    function related(path, paths) {
        for (var i = 0; i < paths.length; i++) {
            if (path === paths[i] || path.indexOf(paths[i] + "/") === 0
                    || paths[i].indexOf(path + "/") === 0) { return true; }
        }
        return false;
    }

    // Close what an earlier reveal opened, but for the nodes above the new match, and
    // put their entries back as they were.
    function undo(earlier, newPath) {
        if (observer) { observer.disconnect(); }
        parts = new Map();
        for (var i = earlier.paths.length - 1; i >= 0; i--) {
            var path = earlier.paths[i];
            if (newPath.indexOf(path + "/") === 0) { continue; }         // above the new match
            if (earlier.before[path]) { map.nodes[path] = earlier.before[path]; }
            else { delete map.nodes[path]; }
            var node = grid.querySelector(".tree-node[data-node=" + quoted(path) + "]");
            if (!node) { continue; }
            var look = lookOf(node);
            showFace(node, look.open, look.why);
            var level = levelOf(node);
            if (level) { reform(level, null); }
            var parent = parentOf(node);
            if (parent) { drawChips(parent); drawFold(parent); }
        }
        write();
        drawBand();
        if (observer) { observer.observe(grid, { childList: true, subtree: true }); }
    }

    // a click or a key anywhere in the page keeps what a reveal opened
    document.addEventListener("pointerdown", endReveal, true);
    document.addEventListener("keydown", endReveal, true);

    // --- the kiosk's memory ------------------------------------------------------------

    if (KIOSK) {
        var idle = null;
        var forget = function () {
            map = empty();
            applyAll(grid);
        };
        var touched = function () {
            clearTimeout(idle);
            idle = setTimeout(forget, KIOSK_IDLE_MS);
        };
        ["pointerdown", "pointermove", "keydown", "wheel"].forEach(function (kind) {
            document.addEventListener(kind, touched, { capture: true, passive: true });
        });
        touched();
    }

    // --- a swap poll.js did not make ---------------------------------------------------

    observer = new MutationObserver(function () {
        if (!swapping) { applyAll(grid); }
    });
    apply(grid, true);
    // what was read is written back once: a map of another version is gone for good
    write();
})();
