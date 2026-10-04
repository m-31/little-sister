/* The ~10s freshness poll shared by the dashboard and the system page
 * (ADR-0005): fetch the page's own URL with ?fragment=1, swap the response
 * into the container named by this script tag's data-target, and keep the
 * #status-updated stamp truthful — "updated …" on success, a red
 * "could not refresh — last ok …" on failure. The stamp is server-seeded
 * (data-rendered-at), so a poll that fails before ever succeeding still
 * reports the page's own render time, not "last ok never".
 *
 * A sustained outage must not look like a blip (ADR-0005): after
 * ESCALATE_AFTER consecutive misses the line grows a legible age, a real
 * banner rises above the content, the frozen content dims (.poll-stale) and
 * the tab title gains a "(stale) " prefix — one good poll resets everything,
 * and a visibilitychange re-poll lets a woken tab self-heal (or alarm) at
 * once. A response without X-Rendered-At is not a fragment at all — the login
 * redirect after session expiry — so it never overwrites the content and
 * escalates immediately with its own "session expired" banner instead of a
 * misleading age.
 *
 * What scrolls sideways inside the swapped part keeps its place: a table wider
 * than a phone stands in a `.table-responsive` box, the fragment brings a new
 * box, and a new box starts at its left edge — every ten seconds, under the
 * thumb of somebody reading its right-hand columns.
 * A curve's frame is such a box too, on a phone, and starts at its right end.
 *
 * The poll waits while a pin's editor is open (ADR-0104 decision 7). On the wall
 * and on a branch's page the editors stand inside what the poll swaps — in a
 * card, in the node's head — and a swap would take the form from under the hands
 * typing in it. So while one is open nothing is fetched and nothing is swapped.
 * The stamp says so at once, "updated … — paused while editing", and after a
 * minute everything but the card being edited dims (.poll-waiting), as a page
 * that lost its server does: a wall left with an editor open must never read as
 * live. When the editor closes the stamp drops the words and the ticks go on,
 * the next one seconds away; a page that had dimmed is brought up to date at
 * once. Not every close is: a swap takes the keyboard's focus with it, and
 * Cancel has just put that back on what opened the editor. An editor is an open
 * disclosure around a `form.maintenance-editor-form`, which is how
 * `_rule_block.html` writes every one of them.
 *
 * A page that is open keeps the stylesheet and the scripts it was loaded with,
 * this one among them, and after an upgrade the markup it is sent was written
 * for others (ADR-0112). So the page states one digest of the files it links —
 * this script tag's data-assets — and every answer states the server's, in
 * X-Assets. Where they differ the page loads itself afresh instead of swapping
 * the answer in: once for a digest, kept in the session's storage, so a server
 * that answers with two digests in turn — two workers either side of an
 * upgrade — reloads a page once and not every ten seconds. It waits for an open
 * editor as every refresh does: nothing is fetched while one is open, so nothing
 * is compared, and what is being typed stays.
 */
(function () {
    var target = document.currentScript &&
        document.currentScript.getAttribute('data-target');
    var container = target ? document.getElementById(target) : null;
    // The digest of the files this page was loaded with, where the page says one.
    var assets = document.currentScript &&
        document.currentScript.getAttribute('data-assets');
    // The digest this session last loaded itself afresh for.
    var RENEWED_FOR = 'ls-assets-renewed-for';
    var stamp = document.getElementById('status-updated');
    if (!container || !stamp) { return; }
    // Consecutive misses before the display escalates — ~1 min at the poll
    // interval, so a dropped poll or a brief restart stays a quiet red line.
    var ESCALATE_AFTER = 6;
    var INTERVAL_MS = 10000;
    // How long the page may wait for an open editor before it dims.
    var WAIT_DIMS_AFTER_MS = 60000;
    var EDITOR = 'details[open] form.maintenance-editor-form';
    var lastOk = stamp.getAttribute('data-rendered-at') || null;
    // Wall clock of the last good response (seeded by the page's own render):
    // ages computed from it stay sane under background-tab timer throttling,
    // and the visibilitychange re-poll corrects a sleep-inflated value fast.
    var lastOkClientMs = Date.now();
    var misses = 0;
    var expired = false;
    var baseTitle = document.title;
    var banner = null;
    // And a curve's frame, which a phone scrolls the drawing in.
    var SCROLLERS = '.table-responsive, .ls-curve__frame';
    // Since when the poll has been waiting for an open editor, or null.
    var waitingSince = null;
    var dimTimer = null;

    function fragmentUrl() {
        var u = new URL(window.location.href);
        u.searchParams.set('fragment', '1');
        return u.toString();
    }
    function age() {
        var s = Math.round((Date.now() - lastOkClientMs) / 1000);
        if (s < 60) { return s + ' s'; }
        if (s < 3600) { return Math.round(s / 60) + ' min'; }
        return Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min';
    }
    function showBanner(html) {
        if (!banner) {
            banner = document.createElement('div');
            banner.className = 'alert alert-danger poll-alert';
            banner.setAttribute('role', 'alert');
            container.parentNode.insertBefore(banner, container);
        }
        banner.innerHTML = html;
    }
    function escalate() {
        var from = lastOk ? ' — the data below is from ' + lastOk : '';
        if (expired) {
            showBanner('<strong>Session expired</strong>' + from +
                       '. <a href="" class="alert-link">Reload to log in</a>.');
        } else {
            showBanner('<strong>No connection to the server</strong> for ' +
                       age() + from + '.');
        }
        container.classList.add('poll-stale');
        if (document.title.indexOf('(stale) ') !== 0) {
            document.title = '(stale) ' + baseTitle;
        }
    }
    function clearEscalation() {
        if (banner) { banner.remove(); banner = null; }
        container.classList.remove('poll-stale');
        document.title = baseTitle;
    }
    function places() {
        return Array.prototype.map.call(
            container.querySelectorAll(SCROLLERS),
            function (box) { return box.scrollLeft; });
    }
    // By position in the fragment, which names no box; one the fragment before
    // did not have starts at its left edge.
    function restore(left) {
        Array.prototype.forEach.call(
            container.querySelectorAll(SCROLLERS),
            function (box, i) { box.scrollLeft = left[i] || 0; });
    }
    function sayUpdated(why) {
        stamp.textContent = 'updated' + (lastOk ? ' ' + lastOk : '') + (why || '');
        // Swap, don't stack: .text-muted sits after .text-danger in
        // Bootstrap's stylesheet and both are !important, so an element
        // carrying both renders muted — the red only shows once muted
        // is removed.
        stamp.classList.add('text-muted');
        stamp.classList.remove('text-danger');
    }
    function sayMissed() {
        var sustained = misses >= ESCALATE_AFTER;
        stamp.textContent = expired
            ? 'session expired — last ok ' + (lastOk || 'never')
            : 'could not refresh' + (sustained ? ' for ' + age() : '') +
              ' — last ok ' + (lastOk || 'never');
        stamp.classList.remove('text-muted');
        stamp.classList.add('text-danger');
        if (sustained || expired) { escalate(); }
    }
    // The server links other files than this page holds: load the page afresh,
    // unless that has been done for this very digest. True when it is on its way.
    function renew(theirs) {
        if (!assets || !theirs || theirs === assets) { return false; }
        try {
            if (window.sessionStorage.getItem(RENEWED_FOR) === theirs) {
                return false;
            }
            window.sessionStorage.setItem(RENEWED_FOR, theirs);
        } catch (e) {
            // No storage to remember it in: a page that could reload every ten
            // seconds is worse than one that keeps its old files.
            return false;
        }
        window.location.reload();
        return true;
    }
    function editing() {
        return container.querySelector(EDITOR) !== null;
    }
    function dim() {
        container.classList.add('poll-waiting');
    }
    // The page stays as it was last read, and says so: the stamp keeps the time
    // of what is shown and adds why it has stopped moving.
    function wait() {
        if (waitingSince !== null) { return; }
        waitingSince = Date.now();
        sayUpdated(' — paused while editing');
        dimTimer = setTimeout(dim, WAIT_DIMS_AFTER_MS);
    }
    // The editor closed: the stamp says again what the last poll left it to say,
    // and the ticks go on. A page that had dimmed is not left to the next of
    // them.
    function resume() {
        if (waitingSince === null) { return; }
        waitingSince = null;
        clearTimeout(dimTimer);
        dimTimer = null;
        if (misses > 0) { sayMissed(); } else { sayUpdated(); }
        if (container.classList.contains('poll-waiting')) {
            container.classList.remove('poll-waiting');
            refresh();
        }
    }
    function refresh() {
        if (editing()) { wait(); return; }
        fetch(fragmentUrl(), {headers: {'X-Requested-With': 'fetch'},
                              cache: 'no-store'})
            .then(function (r) {
                // The server formats this stamp with config.yaml's time_format
                // and timezone (ADR-0006), so it matches every other displayed
                // time instead of the browser's locale. Its absence means this
                // is not a fragment — treat it as a failed poll.
                var renderedAt = r.headers.get('X-Rendered-At');
                if (!r.ok || !renderedAt) {
                    expired = expired || (r.ok && !renderedAt);
                    throw new Error(r.status);
                }
                return r.text().then(function (html) {
                    return {at: renderedAt, html: html,
                            assets: r.headers.get('X-Assets')};
                });
            })
            .then(function (got) {
                // An editor opened while the answer was on its way. What it would
                // replace holds what is being typed, so the answer is dropped
                // whole — its time with it, since the page still shows the older
                // reading.
                if (editing()) { wait(); return; }
                // Markup written for other files than this page holds is not
                // swapped in under them.
                if (renew(got.assets)) { return; }
                lastOk = got.at;
                lastOkClientMs = Date.now();
                var left = places();
                container.innerHTML = got.html;
                restore(left);
                misses = 0;
                expired = false;
                sayUpdated();
                clearEscalation();
            })
            .catch(function () {
                misses += 1;
                // An editor opened while this was on its way: the stamp says
                // the page waits, and says the miss when the editor closes.
                if (waitingSince !== null) { return; }
                sayMissed();
            });
    }
    setInterval(refresh, INTERVAL_MS);
    // A woken laptop or re-focused tab must not wait out the interval (nor
    // show a sleep-inflated age longer than one round trip).
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) { refresh(); }
    });
    // An editor that opens says so at once, not at the next tick, and so does
    // the last one to close. `toggle` does not bubble, hence the capture; the
    // listener is the container's, which no swap replaces.
    container.addEventListener('toggle', function () {
        if (editing()) { wait(); } else { resume(); }
    }, true);
})();
