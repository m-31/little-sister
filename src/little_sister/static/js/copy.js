/* Copy one server-produced status document as Markdown or rich HTML.
 *
 * The Copy page offers one — the tree's, a node's or a line's — and each arrives
 * here as the same three elements, so this script knows nothing about which
 * document it is moving.
 *
 * Both formats come from the same immutable snapshot. The server embeds the
 * hardened HTML as JSON and leaves the Markdown in a selectable textarea; this
 * script only moves those bytes into the browser clipboard after a user click.
 */
(function () {
    'use strict';

    var page = document.getElementById('ls-copy-page');
    var source = document.getElementById('ls-copy-source');
    var htmlPayload = document.getElementById('ls-copy-html');
    var status = document.getElementById('ls-copy-status');
    var details = document.getElementById('ls-copy-source-details');
    if (!page || !source || !htmlPayload || !status) { return; }

    var rich = JSON.parse(htmlPayload.textContent || '""');

    function announce(message) {
        status.textContent = message;
    }

    function selectSource() {
        if (details) { details.open = true; }
        source.focus();
        source.select();
    }

    function legacyCopy(text, html) {
        /* `execCommand` is the compatibility rung, not the primary API. A
         * temporary textarea works even while the visible source details are
         * closed; the boolean return is the only honest success signal it gives.
         *
         * With `html` it carries two members, as the clipboard interface would
         * have written them (ADR-0115 decision 8): the copy event this raises is
         * handed the rendered document beside its Markdown. Outside a secure
         * context — plain http on a host's name, which is how a monitor inside a
         * network is mostly served — that interface does not exist, and this is
         * the only way a page has to the clipboard. Whether the members were set
         * is the handler's to say: a browser that raises no event has copied the
         * selection, which is the Markdown alone. */
        var temporary = document.createElement('textarea');
        temporary.value = text;
        temporary.setAttribute('readonly', '');
        temporary.style.position = 'fixed';
        temporary.style.opacity = '0';
        document.body.appendChild(temporary);
        temporary.select();
        var carried = false;
        function carry(event) {
            if (!html || !event.clipboardData) { return; }
            event.clipboardData.setData('text/html', html);
            event.clipboardData.setData('text/plain', text);
            event.preventDefault();
            carried = true;
        }
        document.addEventListener('copy', carry);
        var copied = false;
        try {
            copied = document.execCommand('copy');
        } finally {
            document.removeEventListener('copy', carry);
            temporary.remove();
        }
        return html ? copied && carried : copied;
    }

    async function writePlain(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                return;
            } catch (_error) {
                /* A browser can expose the API and still deny it for this origin.
                 * Try the compatibility rung before asking for manual selection. */
            }
        }
        if (!legacyCopy(text)) {
            throw new Error('clipboard unavailable');
        }
    }

    function canWriteRich() {
        return Boolean(navigator.clipboard && navigator.clipboard.write &&
                       window.ClipboardItem);
    }

    async function writeRich(markdown) {
        var item = new window.ClipboardItem({
            'text/html': new Blob([rich], {type: 'text/html'}),
            'text/plain': new Blob([markdown], {type: 'text/plain'})
        });
        await navigator.clipboard.write([item]);
        return true;
    }

    page.addEventListener('click', async function (event) {
        var button = event.target.closest('[data-copy-format]');
        if (!button || !page.contains(button)) { return; }
        var format = button.getAttribute('data-copy-format');
        var markdown = source.value;
        button.disabled = true;
        announce('Copying…');
        try {
            if (format === 'rich') {
                var richCopied = false;
                if (canWriteRich()) {
                    try {
                        richCopied = await writeRich(markdown);
                    } catch (_error) {
                        richCopied = false;
                    }
                }
                /* The second rung. Where the interface is missing nothing was
                 * awaited before it, and that matters: a browser lets a page
                 * copy only while it is still answering the click. */
                if (!richCopied) {
                    richCopied = legacyCopy(markdown, rich);
                }
                if (richCopied) {
                    announce('Rich HTML copied.');
                } else {
                    await writePlain(markdown);
                    announce('Rich HTML is unavailable; Markdown copied instead.');
                }
            } else {
                await writePlain(markdown);
                announce('Markdown copied.');
            }
        } catch (_error) {
            selectSource();
            announce('Clipboard access failed. The Markdown is selected for manual copying.');
        } finally {
            button.disabled = false;
        }
    });
}());
