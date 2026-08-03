/* The /about hero: hand the eyes from one signal to the next.
 *
 * Everything else on this page is CSS — the rings turn, the labels stay upright,
 * the lines take their turn and stop. This file exists for the one thing a
 * stylesheet cannot say: **which term the eyes are on**, and that the sentence
 * naming that term in the paragraph below should light with it. No selector
 * relates two elements that far apart, so a few lines of JavaScript relate them.
 *
 * It does not read geometry. The rings turn at a constant rate, so *whose turn
 * it is* is arithmetic, not measurement: every few seconds the next term is
 * seen, in the order the markup declares. That keeps the glow and the phrase in
 * step by construction, and it costs one timer.
 *
 * Two things it refuses to do:
 *
 * - **Start at all when the viewer asked for reduced motion.** A term lighting
 *   up on its own is motion, whatever it is worth; the page still says
 *   everything it has to say, in the prose that was always the real content.
 * - **Keep going while the tab is hidden.** It resumes where it stopped — the
 *   same shape poll.js uses.
 */
(function () {
    var hero = document.getElementById('ls-hero');
    if (!hero) { return; }

    if (window.matchMedia
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }

    var signals = hero.querySelectorAll('.ls-hero__signal');
    if (!signals.length) { return; }

    /* How long the eyes rest on one term. Slow enough to read, and slow enough
     * that a glance at the page catches at most one change — this is the
     * background of a page about watching, not a slideshow. */
    var DWELL = 3200;

    var current = -1;
    var timer = null;

    function light(element, on) {
        if (element) { element.classList.toggle('is-seen', on); }
    }

    function topic(element) {
        /* The phrase in the story that this term names, if it names one. Most
         * terms do not: they are the weather, not the paragraph. */
        var name = element.getAttribute('data-topic');
        return name
            ? document.querySelector('.ls-topic[data-topic="' + name + '"]')
            : null;
    }

    function look() {
        if (current >= 0) {
            light(signals[current], false);
            light(topic(signals[current]), false);
        }
        current = (current + 1) % signals.length;
        light(signals[current], true);
        light(topic(signals[current]), true);
        timer = window.setTimeout(look, DWELL);
    }

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            window.clearTimeout(timer);
        } else {
            window.clearTimeout(timer);
            timer = window.setTimeout(look, DWELL);
        }
    });

    look();
})();
