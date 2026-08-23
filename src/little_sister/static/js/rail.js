/* Sticky chrome and the rail's burger.
 *
 * The rail sits below a Bootstrap navbar whose rendered height is content, not
 * a contract: the top-bar collapse changes it, and a brand or padding change can
 * too. CSS supplies safe scriptless estimates; a ResizeObserver progressively
 * refines both the rendered border-box height and, when navigation starts below
 * the settings row, the non-section footprint around it (that row plus bar inset).
 * The fallback follows window resizes in older browsers.
 *
 * The burger swaps the collapsed icon rail for icons + labels. Deliberately not
 * remembered: collapsed-to-icons is the layout's default, so the burger is a
 * peek at the labels rather than a setting — every page starts collapsed.
 * Presentation that *is* remembered (theme, layout) belongs to the one long-lived
 * cookie that owns it (ADR-0029); a second store competing is exactly what that
 * decision avoids.
 */
(function () {
    var bar = document.querySelector('.ls-bar');
    if (bar) {
        var nav = bar.querySelector('.ls-bar__nav');
        var who = bar.querySelector('.ls-bar__who');
        var measureBar = function () {
            var barBox = bar.getBoundingClientRect();
            var rowBudget = barBox.height;
            if (nav && who) {
                var navBox = nav.getBoundingClientRect();
                var whoBox = who.getBoundingClientRect();
                if (navBox.height > 0 && navBox.top >= whoBox.bottom) {
                    rowBudget = barBox.height - navBox.height;
                }
            }
            document.documentElement.style.setProperty(
                '--ls-bar-height', barBox.height + 'px');
            document.documentElement.style.setProperty(
                '--ls-bar-row-budget', rowBudget + 'px');
        };
        measureBar();
        if ('ResizeObserver' in window) {
            var observer = new ResizeObserver(measureBar);
            // The offset is the rendered border-box height. Observing the
            // default content box would miss a theme changing the bar's padding.
            observer.observe(bar, {box: 'border-box'});
        } else {
            window.addEventListener('resize', measureBar);
        }
    }

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
