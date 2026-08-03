/* The rail's burger: swaps the collapsed icon rail for
 * icons + labels.
 *
 * Deliberately not remembered. Collapsed-to-icons is the layout's default, so
 * the burger is a peek at the labels rather than a setting — every page starts
 * collapsed. Presentation that *is* remembered (theme, layout) belongs to the
 * one long-lived cookie that owns it (ADR-0029); a second store competing is
 * exactly what that decision avoids.
 */
(function () {
    var rail = document.getElementById('ls-rail');
    var burger = rail && rail.querySelector('.ls-rail__burger');
    if (!burger) { return; }
    burger.addEventListener('click', function () {
        var expanded = rail.classList.toggle('is-expanded');
        burger.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        burger.setAttribute('aria-label', expanded
            ? 'Collapse the section labels'
            : 'Expand the section labels');
    });
})();
