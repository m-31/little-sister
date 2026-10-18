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
 * Without JavaScript each of the two forms keeps a `<noscript>` submit button, so a
 * choice can still be applied.
 */
(function () {
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
        /* `submit()`, deliberately, not `requestSubmit()`: the attribute this
         * replaces skipped constraint validation, and the depth field has a
         * min/max. Validating here would start refusing an out-of-range depth in
         * the browser that the server has always simply clamped — a behavior change
         * with no business in a move-the-handler slice. */
        form.submit();
    });
})();
