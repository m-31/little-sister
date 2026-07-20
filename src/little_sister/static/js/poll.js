/* The ~10s freshness poll shared by the dashboard and the system page
 * (ADR-0005): fetch the page's own URL with ?fragment=1, swap the response
 * into the container named by this script tag's data-target, and keep the
 * #status-updated stamp truthful — "updated …" on success, a red
 * "could not refresh — last ok …" on failure. The stamp is server-seeded
 * (data-rendered-at), so a poll that fails before ever succeeding still
 * reports the page's own render time, not "last ok never".
 *
 * A sustained outage must not look like a blip (ADR-0005 update note): after
 * ESCALATE_AFTER consecutive misses the line grows a legible age, a real
 * banner rises above the content, the frozen content dims (.poll-stale) and
 * the tab title gains a "(stale) " prefix — one good poll resets everything,
 * and a visibilitychange re-poll lets a woken tab self-heal (or alarm) at
 * once. A response without X-Rendered-At is not a fragment at all — the login
 * redirect after session expiry — so it never overwrites the content and
 * escalates immediately with its own "session expired" banner instead of a
 * misleading age.
 */
(function () {
    var target = document.currentScript &&
        document.currentScript.getAttribute('data-target');
    var container = target ? document.getElementById(target) : null;
    var stamp = document.getElementById('status-updated');
    if (!container || !stamp) { return; }
    // Consecutive misses before the display escalates — ~1 min at the poll
    // interval, so a dropped poll or a brief restart stays a quiet red line.
    var ESCALATE_AFTER = 6;
    var INTERVAL_MS = 10000;
    var lastOk = stamp.getAttribute('data-rendered-at') || null;
    // Wall clock of the last good response (seeded by the page's own render):
    // ages computed from it stay sane under background-tab timer throttling,
    // and the visibilitychange re-poll corrects a sleep-inflated value fast.
    var lastOkClientMs = Date.now();
    var misses = 0;
    var expired = false;
    var baseTitle = document.title;
    var banner = null;

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
    function refresh() {
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
                lastOk = renderedAt;
                lastOkClientMs = Date.now();
                return r.text();
            })
            .then(function (html) {
                container.innerHTML = html;
                misses = 0;
                expired = false;
                stamp.textContent = 'updated' + (lastOk ? ' ' + lastOk : '');
                // Swap, don't stack: .text-muted sits after .text-danger in
                // Bootstrap's stylesheet and both are !important, so an element
                // carrying both renders muted — the red only shows once muted
                // is removed.
                stamp.classList.add('text-muted');
                stamp.classList.remove('text-danger');
                clearEscalation();
            })
            .catch(function () {
                misses += 1;
                var sustained = misses >= ESCALATE_AFTER;
                stamp.textContent = expired
                    ? 'session expired — last ok ' + (lastOk || 'never')
                    : 'could not refresh' + (sustained ? ' for ' + age() : '') +
                      ' — last ok ' + (lastOk || 'never');
                stamp.classList.remove('text-muted');
                stamp.classList.add('text-danger');
                if (sustained || expired) { escalate(); }
            });
    }
    setInterval(refresh, INTERVAL_MS);
    // A woken laptop or re-focused tab must not wait out the interval (nor
    // show a sleep-inflated age longer than one round trip).
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) { refresh(); }
    });
})();
