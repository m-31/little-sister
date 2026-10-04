/* A Series view's drag and its line (ADR-0098 decision 6).
 *
 * Everything this file does, a link on the page already does: the bar's presets
 * and moves, and every stretch of a time axis, lead to the window they name, and
 * the server draws every curve. What this file adds is the hand.
 *
 * - A drag across a curve's plot or its time axis, with a mouse or a pen, marks the
 *   stretch on every curve and writes its two ends beneath the curve dragged; let
 *   go, it opens the view over it: `from` and `to` as two instants, rounded to the
 *   minute over a window of an hour or more and to the second under one, returning
 *   to the curve's group — the link a stretch of the axis would be. A drag shorter
 *   than a few pixels is a click, and on an axis the link it lands on; Escape lets
 *   a drag go.
 * - Where the pointer rests on a plot, one line crosses every plot at that instant,
 *   and each curve's summary says what its strip there says. The server wrote those
 *   words as each strip's title; this file moves them to where the eye already is —
 *   laid over the summary on one line, never in its place, so that no caption grows
 *   or shrinks and nothing below it moves while the line does. The strips stop taking
 *   the pointer (the stylesheet, on `.is-enhanced`), so their tooltips do not say it
 *   a second time.
 * - A preset or a move from the bar returns to the group the view was scrolled to,
 *   by that group's anchor, as a stretch's link does.
 *
 * Touch is left alone: a drag there scrolls the page, and a tap is the link it
 * lands on. Nothing here reads the clock: a drag names instants the drawing already
 * stands for, from the window's ends the grid carries (`data-start`, `data-end`)
 * and where each plot draws them (`data-left`, `data-right`).
 */
(function () {
    'use strict';

    var grid = document.querySelector('.ls-series-grid[data-start][data-end]');
    if (!grid || !window.PointerEvent) { return; }
    var start = Date.parse(grid.getAttribute('data-start'));
    var end = Date.parse(grid.getAttribute('data-end'));
    var plots = [].slice.call(grid.querySelectorAll('svg.ls-curve__plot[data-left]'));
    if (!(end > start) || !plots.length) { return; }

    var SVG = 'http://www.w3.org/2000/svg';
    /* Fewer pixels than this between press and release is a click, not a drag. */
    var FEW = 4;
    /* A stretch's ends are rounded to the minute over a window of an hour or more,
       and to the second under one. */
    var STEP = end - start >= 3600000 ? 60000 : 1000;
    var clock = formatter(grid.getAttribute('data-zone') || undefined);
    var bar = document.querySelector('.ls-window');

    /* Each plot as this file reads it: where the window stands on it and how tall
       its strips run, its strips' edges and words, and the summary that says them. */
    var drawings = plots.map(function (plot) {
        var figure = plot.closest('figure');
        var summary = figure ? figure.querySelector('.ls-curve__summary') : null;
        var next = plot.nextElementSibling;
        var reading = summary ? over(summary) : null;
        return {
            plot: plot,
            axis: next && next.matches('svg.ls-curve__axis') ? next : null,
            group: plot.closest('section[id]'),
            left: number(plot, 'data-left'),
            right: number(plot, 'data-right'),
            top: number(plot, 'data-top'),
            bottom: number(plot, 'data-bottom'),
            width: plot.viewBox.baseVal.width,
            strips: [].slice.call(plot.querySelectorAll('.ls-curve__hover rect'))
                .map(function (rect) {
                    var title = rect.querySelector('title');
                    var x = number(rect, 'x');
                    return {from: x, to: x + number(rect, 'width'),
                            said: title ? title.textContent : ''};
                }),
            summary: summary,
            reading: reading,
            shown: null,
            cross: null,
            band: null,
            ends: null
        };
    });
    grid.classList.add('is-enhanced');

    var drag = null;
    /* The click that ends a drag, or that follows one let go, is not a link's. */
    var swallow = false;

    grid.addEventListener('pointerdown', function (event) {
        swallow = false;
        if (event.pointerType === 'touch' || event.button !== 0 || !event.isPrimary) {
            return;
        }
        var drawing = drawingOf(event.target);
        if (!drawing) { return; }
        // nothing selected as text, nothing picked up as a link
        event.preventDefault();
        var x = unitAt(drawing, event.clientX);
        drag = {drawing: drawing, from: x, to: x, x0: event.clientX,
                id: event.pointerId, moved: false};
    });

    // a link is a picture's too: nothing on a drawing is picked up and carried off
    grid.addEventListener('dragstart', function (event) {
        if (drawingOf(event.target)) { event.preventDefault(); }
    });

    grid.addEventListener('pointermove', function (event) {
        if (event.pointerType === 'touch') { return; }
        if (drag && event.pointerId === drag.id) {
            if (!drag.moved) {
                if (Math.abs(event.clientX - drag.x0) < FEW) { return; }
                // a drag now, not a click: the pointer is the view's until let go,
                // wherever it wanders — and only now, or a click on an axis would
                // land on the grid instead of on the stretch's link
                drag.moved = true;
                try { grid.setPointerCapture(drag.id); } catch (ignored) { /* gone */ }
            }
            drag.to = unitAt(drag.drawing, event.clientX);
            mark(drag);
            show(drag.to);
            return;
        }
        var drawing = drawingOf(event.target);
        if (drawing) { show(unitAt(drawing, event.clientX)); } else { hide(); }
    });

    grid.addEventListener('pointerup', function (event) {
        if (!drag || event.pointerId !== drag.id) { return; }
        var done = drag;
        drag = null;
        release(event.pointerId);
        if (!done.moved) { return; }
        swallow = true;
        var ends = chosen(done);
        location.assign(location.pathname + '?from=' + instant(ends[0]) + '&to='
                        + instant(ends[1])
                        + (done.drawing.group ? '#' + done.drawing.group.id : ''));
    });

    grid.addEventListener('pointercancel', function (event) {
        if (!drag) { return; }
        drag = null;
        release(event.pointerId);
        clear();
    });

    grid.addEventListener('pointerleave', function () {
        if (!drag) { hide(); }
    });

    grid.addEventListener('click', function (event) {
        // a click the keyboard made (`detail` 0) was never a drag's
        if (!swallow || event.detail === 0) { return; }
        swallow = false;
        event.preventDefault();
        event.stopPropagation();
    }, true);

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape' || !drag) { return; }
        var id = drag.id;
        drag = null;
        swallow = true;
        release(id);
        clear();
    });

    if (bar) {
        bar.addEventListener('click', function (event) {
            var link = event.target.closest('a.ls-window__link[href]');
            if (!link) { return; }
            var group = inView();
            var href = link.getAttribute('href').split('#')[0];
            link.setAttribute('href', group ? href + '#' + group.id : href);
        });
    }

    /* The group the view was scrolled to: the first whose foot is still below the
       bar — or none, where the view is at its top and the grid starts below it. */
    function inView() {
        var edge = bar ? bar.getBoundingClientRect().bottom : 0;
        if (grid.getBoundingClientRect().top >= edge) { return null; }
        var groups = grid.querySelectorAll('section[id]');
        for (var index = 0; index < groups.length; index++) {
            if (groups[index].getBoundingClientRect().bottom > edge) {
                return groups[index];
            }
        }
        return null;
    }

    /* The drawing a pointer is over: a plot, or the time axis beneath it. */
    function drawingOf(target) {
        var svg = target && target.closest
            ? target.closest('svg.ls-curve__plot, svg.ls-curve__axis') : null;
        if (!svg) { return null; }
        var plot = svg.matches('svg.ls-curve__axis') ? svg.previousElementSibling : svg;
        for (var index = 0; index < drawings.length; index++) {
            if (drawings[index].plot === plot) { return drawings[index]; }
        }
        return null;
    }

    /* Where a pointer stands on a drawing, in its units, kept inside the window. */
    function unitAt(drawing, clientX) {
        var box = drawing.plot.getBoundingClientRect();
        var x = (clientX - box.left) / box.width * drawing.width;
        return Math.min(drawing.right, Math.max(drawing.left, x));
    }

    function momentAt(drawing, x) {
        return start + (x - drawing.left) / (drawing.right - drawing.left) * (end - start);
    }

    function unitOf(drawing, moment) {
        var x = drawing.left
            + (moment - start) / (end - start) * (drawing.right - drawing.left);
        return Math.min(drawing.right, Math.max(drawing.left, x));
    }

    /* The two instants a drag chooses, rounded, the earlier first. */
    function chosen(drag) {
        var ends = [drag.from, drag.to].map(function (x) {
            return Math.round(momentAt(drag.drawing, x) / STEP) * STEP;
        }).sort(function (a, b) { return a - b; });
        if (ends[1] <= ends[0]) { ends[1] = ends[0] + STEP; }
        return ends;
    }

    /* The stretch a drag chooses, marked on every plot, and its ends written
       beneath the curve dragged, where the axis's own labels give way to them. */
    function mark(drag) {
        var ends = chosen(drag);
        drawings.forEach(function (drawing) {
            var low = unitOf(drawing, ends[0]);
            var high = unitOf(drawing, ends[1]);
            if (!drawing.band) {
                drawing.band = element('rect', {'class': 'ls-curve__band',
                                                y: drawing.top,
                                                height: drawing.bottom - drawing.top});
                drawing.plot.insertBefore(drawing.band, drawing.plot.firstChild);
            }
            drawing.band.setAttribute('x', low.toFixed(1));
            drawing.band.setAttribute('width', (high - low).toFixed(1));
            drawing.band.style.display = '';
        });
        var drawing = drag.drawing;
        if (!drawing.axis) { return; }
        drawing.axis.classList.add('is-choosing');
        if (!drawing.ends) {
            var baseline = drawing.axis.querySelector('.ls-curve__time');
            var y = baseline ? baseline.getAttribute('y') : '15';
            drawing.ends = [0, 1].map(function () {
                var text = element('text', {'class': 'ls-curve__chosen', y: y});
                drawing.axis.appendChild(text);
                return text;
            });
        }
        var low = unitOf(drawing, ends[0]);
        var high = unitOf(drawing, ends[1]);
        place(drawing.ends[0], written(ends[0]), low - 3 < 48 ? low + 3 : low - 3,
              low - 3 < 48 ? 'start' : 'end');
        place(drawing.ends[1], written(ends[1]),
              high + 3 > drawing.width - 48 ? high - 3 : high + 3,
              high + 3 > drawing.width - 48 ? 'end' : 'start');
    }

    function place(text, words, x, anchor) {
        text.textContent = words;
        text.setAttribute('x', x.toFixed(1));
        text.setAttribute('text-anchor', anchor);
        text.style.display = '';
    }

    function clear() {
        drawings.forEach(function (drawing) {
            if (drawing.band) { drawing.band.style.display = 'none'; }
            if (drawing.axis) { drawing.axis.classList.remove('is-choosing'); }
            if (drawing.ends) {
                drawing.ends.forEach(function (text) { text.style.display = 'none'; });
            }
        });
    }

    /* The line at one instant on every plot, and what each curve's strip there says
       in its summary — or its own summary, where no strip is. */
    function show(x) {
        drawings.forEach(function (drawing) {
            if (!drawing.cross) {
                drawing.cross = element('line', {'class': 'ls-curve__cross',
                                                 y1: drawing.top, y2: drawing.bottom});
                drawing.plot.appendChild(drawing.cross);
            }
            var at = unitOf(drawing, momentAt(drawing, x));
            drawing.cross.setAttribute('x1', at.toFixed(1));
            drawing.cross.setAttribute('x2', at.toFixed(1));
            drawing.cross.style.display = '';
            say(drawing, stripAt(drawing, at));
        });
    }

    function hide() {
        drawings.forEach(function (drawing) {
            if (drawing.cross) { drawing.cross.style.display = 'none'; }
            say(drawing, null);
        });
    }

    function say(drawing, strip) {
        if (!drawing.reading || drawing.shown === strip) { return; }
        drawing.shown = strip;
        var summary = drawing.summary;
        var reading = drawing.reading;
        if (strip) {
            reading.style.left = summary.offsetLeft + 'px';
            reading.style.top = summary.offsetTop + 'px';
            reading.textContent = strip.said;
            reading.hidden = false;
            summary.style.visibility = 'hidden';
        } else {
            reading.hidden = true;
            summary.style.visibility = '';
        }
    }

    /* The line's reading for a curve, beside its summary in the caption: the
       stylesheet lays it over the summary on one line (`.ls-curve__reading`), and
       `say` writes where the summary begins. */
    function over(summary) {
        var reading = document.createElement('span');
        reading.className = 'ls-curve__summary ls-curve__reading';
        reading.setAttribute('aria-hidden', 'true');
        reading.hidden = true;
        summary.parentNode.appendChild(reading);
        return reading;
    }

    /* The strip beneath `x`: the strips run left to right, each to where the next
       begins, the last to the plot's edge. */
    function stripAt(drawing, x) {
        var strips = drawing.strips;
        var low = 0;
        var high = strips.length - 1;
        while (low <= high) {
            var middle = (low + high) >> 1;
            var strip = strips[middle];
            if (x < strip.from) {
                high = middle - 1;
            } else if (x > strip.to || (x === strip.to && middle < strips.length - 1)) {
                low = middle + 1;
            } else {
                return strip;
            }
        }
        return null;
    }

    function release(id) {
        try {
            if (grid.hasPointerCapture(id)) { grid.releasePointerCapture(id); }
        } catch (ignored) { /* gone */ }
    }

    function element(name, attributes) {
        var node = document.createElementNS(SVG, name);
        Object.keys(attributes).forEach(function (key) {
            node.setAttribute(key, attributes[key]);
        });
        return node;
    }

    function number(node, name) {
        return parseFloat(node.getAttribute(name));
    }

    /* An instant as a link writes one: UTC, to the second, with a `Z`. */
    function instant(moment) {
        return new Date(moment).toISOString().replace(/\.\d{3}Z$/, 'Z');
    }

    /* An instant as the axis writes one, in the configured zone: `17:15`, to the
       second under an hour, and with the date where the window runs over days. */
    function written(moment) {
        var parts = {};
        clock.formatToParts(new Date(moment)).forEach(function (part) {
            parts[part.type] = part.value;
        });
        var time = parts.hour + ':' + parts.minute
            + (STEP < 60000 ? ':' + parts.second : '');
        return end - start > 86400000 ? parts.month + '-' + parts.day + ' ' + time : time;
    }

    function formatter(zone) {
        var options = {year: 'numeric', month: '2-digit', day: '2-digit',
                       hour: '2-digit', minute: '2-digit', second: '2-digit',
                       hourCycle: 'h23', timeZone: zone};
        try {
            return new Intl.DateTimeFormat('en-GB', options);
        } catch (unknown) {
            delete options.timeZone;
            return new Intl.DateTimeFormat('en-GB', options);
        }
    }
})();
