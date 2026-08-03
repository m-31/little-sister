/* The links page's two behaviors: the icon fallback, and the filter box.
 *
 * Both are written to survive a **fragment swap**. This page does not poll today,
 * but every other live surface here does, and a script that only works on the
 * markup that happened to be in the document at load is the kind of thing that
 * breaks silently the day polling arrives. So: no per-element listeners bound once
 * (the icon handler is delegated), and a MutationObserver re-applies the filter to
 * whatever markup is there now — the same shape reasons.js, branches.js and
 * maintenance.js already use.
 */
(function () {
    var page = document.getElementById('ls-links-page');
    if (!page) { return; }

    /* ---- the icon fallback (ADR-0030 §3) -------------------------------------
     *
     * The last step of the search path: an icon that fails to load is replaced by
     * the neutral glyph, so the page never shows a browser's broken-image icon.
     *
     * Delegated, and attached here rather than written as an `onerror` attribute
     * on every image — an inline handler would be the one reason a
     * Content-Security-Policy could not be turned on later, and the ADR names it.
     * `error` does not bubble, so this listens in the **capture** phase, which is
     * also what makes it reach an image that arrived after load.
     *
     * The swap is per image, not per entry, because an icon may be a light/dark
     * *pair* — losing the file for one background must not take the working one
     * for the other with it. The glyph inherits the failed image's variant class,
     * so it appears in exactly the theme the missing file was for.
     */
    var template = document.getElementById('ls-links-glyph');

    function fallback(image) {
        var mark = image.closest('.ls-links__mark');
        if (!template || !mark) { return; }
        var glyph = template.content.firstElementChild.cloneNode(true);
        glyph.setAttribute('class', image.getAttribute('class'));
        glyph.setAttribute('width', '20');
        glyph.setAttribute('height', '20');
        image.replaceWith(glyph);
        /* The chip exists to keep a *file* legible in every theme. A glyph in
         * currentColor already is — and on a dark theme it would be a light
         * drawing on the chip's light face, which is the one arrangement that
         * disappears. So the chip goes once no image is left behind it. */
        if (!mark.querySelector('img')) {
            mark.classList.remove('ls-links__mark--chip');
        }
    }

    page.addEventListener('error', function (event) {
        var image = event.target;
        if (image && image.classList &&
            image.classList.contains('ls-links__icon')) {
            fallback(image);
        }
    }, true);

    function sweepBrokenImages() {
        /* An image that failed *before* this script ran fires no event of its own
         * — a cached 404 on a fast page is exactly that case — and neither does
         * one that failed between a swap and the observer's callback. */
        var images = page.querySelectorAll('img.ls-links__icon');
        for (var i = 0; i < images.length; i++) {
            if (images[i].complete && images[i].naturalWidth === 0) {
                fallback(images[i]);
            }
        }
    }

    /* ---- the filter box ------------------------------------------------------
     *
     * A page that grows to sixty entries is navigated by typing, not by reading:
     * the filter is the primary navigation, which is why it is focused on arrival
     * and why it costs no round trip. Entries are *records*, so matching is a
     * string compare against the one field the server put in `data-ls-match` —
     * never a search over rendered prose (ADR-0030).
     *
     * Every token must match, in any order, so "graf live" narrows rather than
     * widens. Order is never touched: this hides, it does not sort — an operator
     * who put EMERGENCY STOP first meant it, filtered or not.
     */
    var input = document.getElementById('ls-links-filter');
    var count = document.getElementById('ls-links-count');
    var empty = document.getElementById('ls-links-none');

    function apply() {
        if (!input) { return; }
        var tokens = input.value.toLowerCase().split(/\s+/).filter(Boolean);
        var groups = page.querySelectorAll('.ls-links__group');
        var shown = 0;
        var total = 0;
        for (var g = 0; g < groups.length; g++) {
            var entries = groups[g].querySelectorAll('.ls-links__entry');
            var visible = 0;
            for (var e = 0; e < entries.length; e++) {
                var hay = entries[e].getAttribute('data-ls-match') || '';
                var hit = tokens.every(function (token) {
                    return hay.indexOf(token) !== -1;
                });
                entries[e].hidden = !hit;
                if (hit) { visible++; }
            }
            /* A heading with nothing under it is noise while filtering — but the
             * group is only hidden, never removed, so clearing the box puts the
             * page back exactly as the file wrote it. */
            groups[g].hidden = visible === 0;
            shown += visible;
            total += entries.length;
        }
        if (count) {
            count.hidden = tokens.length === 0;
            count.textContent = shown + ' of ' + total;
        }
        if (empty) { empty.hidden = !(tokens.length && shown === 0); }
    }

    if (input) {
        input.addEventListener('input', apply);
        input.addEventListener('keydown', function (event) {
            /* Escape clears rather than blurring: on a page whose whole job is
             * finding one link, getting back to all of them is the common move. */
            if (event.key === 'Escape' && input.value) {
                input.value = '';
                apply();
                event.preventDefault();
            }
        });
    }

    var observer = null;

    function refresh() {
        /* Detach while we mutate — swapping a glyph in and setting `hidden` are
         * both DOM changes, and an observer that watched its own edits would loop
         * forever. Reattach when done. (Same guard reasons.js uses.) */
        if (observer) { observer.disconnect(); }
        sweepBrokenImages();
        apply();
        if (observer) {
            observer.observe(page, {childList: true, subtree: true});
        }
    }

    /* Re-apply to markup that arrived after load. The filter is a property of the
     * viewer, not of the response, so a swap must not quietly show them entries
     * they have filtered away. */
    observer = new MutationObserver(refresh);
    refresh();
})();
