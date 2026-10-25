/* Submit-on-change for the presentation controls (ADR-0029): the dashboard's
 * filter switches and the settings menu's theme/layout radios.
 *
 * These were `onchange="this.form.submit()"` attributes on each input. An inline
 * handler is the one thing a Content-Security-Policy can neither hash nor nonce —
 * only `'unsafe-hashes'` admits it, and that is a keyword ADR-0048 will not take
 * from anyone but the deployment — so the attributes moved here, the same way the
 * links page declines an `onerror` for exactly this reason. A control opts in by
 * carrying `data-ls-submit`.
 *
 * **Delegated on the document, not bound per element.** The band rides the ~10s
 * poll fragment on the dashboard, so listeners attached to the markup that happened
 * to be in the document at load would stop working after the first swap —
 * silently, and only on the pages that poll. The same shape links.js, tree.js
 * and maintenance.js already use. `change` bubbles, so one listener
 * reaches a control that arrived after load without a MutationObserver.
 *
 * **The settings menu stands open through a choice**
 * A choice reloads the page, the server drawing the look it names; before the form
 * goes, the choice is written to the tab's session storage, and the page it brings
 * back opens the menu again with the focus on that choice, the entry read once and
 * removed. Where the storage is refused the menu stays shut, as it always did; a
 * filter switch, outside the menu, writes nothing.
 *
 * Without JavaScript each of the two forms keeps a `<noscript>` submit button, so a
 * choice can still be applied.
 */
(function () {
    var REOPEN = 'ls-menu-reopen';

    document.addEventListener('change', function (event) {
        var control = event.target;
        if (!control || !control.getAttribute ||
            control.getAttribute('data-ls-submit') === null) {
            return;
        }
        /* `form` is null for a control outside one — not markup this surface
         * produces, and not worth a thrown error the day it is. */
        var form = control.form;
        if (!form) { return; }
        if (control.closest && control.closest('.ls-menu__panel')) {
            try {
                window.sessionStorage.setItem(
                    REOPEN, JSON.stringify([control.name, control.value]));
            } catch (e) { /* the menu stays shut on the page the choice brings */ }
        }
        /* `submit()`, deliberately, not `requestSubmit()`: the attribute this
         * replaces skipped constraint validation, and the depth field has a
         * min/max. Validating here would start refusing an out-of-range depth in
         * the browser that the server has always simply clamped — a behavior change
         * with no business in a move-the-handler slice. */
        form.submit();
    });

    // The page a choice brought: the menu open again, the focus on the choice.
    function reopen() {
        var chosen = null;
        try {
            chosen = JSON.parse(window.sessionStorage.getItem(REOPEN) || 'null');
            window.sessionStorage.removeItem(REOPEN);
        } catch (e) { return; }
        if (!Array.isArray(chosen) || chosen.length !== 2) { return; }
        var trigger = document.getElementById('ls-settings');
        var dropdown = window.bootstrap && window.bootstrap.Dropdown;
        if (!trigger || !dropdown) { return; }
        dropdown.getOrCreateInstance(trigger).show();
        var radios = document.querySelectorAll('.ls-menu__panel input[type=radio]');
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].name === chosen[0] && radios[i].value === chosen[1]) {
                radios[i].focus({ preventScroll: true });
                return;
            }
        }
    }

    // `defer`red, this runs once the document is parsed and before
    // DOMContentLoaded, by which time the end-of-body Bootstrap bundle has run.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', reopen);
    } else {
        reopen();
    }
})();
