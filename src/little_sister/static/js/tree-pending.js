/* Before the first paint: say the page has its scripts, and hide the grid while the
 * tab's map holds anything.
 *
 * `tree.js` (ADR-0127 decision 10) puts the map back on a load before the first
 * paint, but it is linked after the grid, and a long wall paints while the parser is
 * still on its way there — a viewer would see the first look flash before their folds
 * come back, and what the script shows would move the page once it runs. So this file
 * is linked in the head, without `defer`. First it puts `ls-script` on <html>, under
 * which `overview.css` draws from the first paint what `tree.js` will show — the
 * band's three buttons, and on a node's page the head's ‖ in the place of *Set
 * maintenance* — so neither moves the page when the script runs; a page without
 * script has neither, and its setter beneath the head. Then it reads the map's key
 * and, where the map holds a node's entry or a mode, puts `ls-tree-pending` on
 * <html>, under which `overview.css` hides `#status-grid` — and a leaf's page,
 * `.node-page`, which has a frame and no grid — with `visibility: hidden`, not
 * `display: none`, so that what `tree.js` and `dashboard-layout.js` measure meanwhile
 * is measured right. `tree.js` takes the class off once the map is applied; a
 * one-second timer takes it off whatever happens, so a script that never ran leaves
 * no blank wall. A tab with an empty map, as every first visit has, hides nothing,
 * and a page with neither is untouched.
 *
 * Under the look `boxes: packed` (ADR-0138) the boxes take their columns once
 * `tree.js` has put the map back, and `overview.css` hides `#status-grid` under
 * `ls-script` until `tree.js` puts `ls-boxes-drawn` on <html>, lest the first paint
 * stand them in rows for the packing to move; this file cannot tell the look, which
 * is on the body still to be parsed, so its second timer puts the class there after
 * a second whatever the look, for a script that never ran.
 *
 * An external script rather than a second inline one: the content security policy
 * names one inline script by its hash, the theme's (`_theme_bootstrap.html`,
 * ADR-0048), and a second hash would be a change to the policy.
 */
(function () {
    "use strict";
    var html = document.documentElement;
    html.classList.add("ls-script");
    setTimeout(function () { html.classList.add("ls-boxes-drawn"); }, 1000);
    var raw = null;
    try { raw = window.sessionStorage.getItem("ls-wall-map"); } catch (e) { return; }
    if (!raw) { return; }
    var map;
    try { map = JSON.parse(raw); } catch (e) { return; }
    if (!map || !map.nodes) { return; }
    // a mode in force — *Close all*, *Open all* — redraws every node, as an entry does
    if (!Object.keys(map.nodes).length && !map.mode) { return; }
    html.classList.add("ls-tree-pending");
    setTimeout(function () { html.classList.remove("ls-tree-pending"); }, 1000);
})();
