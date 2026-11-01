/* Read-to-edit maintenance disclosures (ADR-0014, ADR-0104).
 *
 * The disclosure itself is native <details>, so every node/entry form remains
 * usable without JavaScript.  This small enhancement gives the explicit Cancel
 * button and Escape the same meaning: reset the raw Markdown/duration fields,
 * return to rendered read mode, and put focus back on the control that opened it.
 * An editor opens in its note, at the note's end,
 * and an expiry field that is still as it was filled is selected when it takes
 * focus.  The ringed check's editor holds two forms, *Seen* and *Silence*, one in
 * view at a time (ADR-0144) — and a block's a third, *Done*, where its part takes one
 * (ADR-0146): Cancel resets each and the choice between them, the editor opens in the
 * note of the one in view, and a note written in one is the others' too, so that
 * changing one's mind about the kind keeps what was written.
 * A node's Notes tab builds its form the same way over every kind the reader may
 * set (ADR-0145 decision 2): the words are one field across them, and so is the
 * part chosen under *On*, wherever the kind chosen may be set on it.
 *
 * A maintenance entry's editor (ADR-0150, landing 4) keeps the rest of its fields —
 * a repeat's days, *Until*, *Not on*, the zone, *Add an interval* and what it would
 * set — in the browser's own disclosure, and without script each of its buttons sends
 * the editor back with what it did. Here the rest opens in place as a repeat or a
 * start is chosen, and what it would set follows the fields: the part beneath them
 * is asked of the server, the same rendering a preview draws, and put in place, so
 * that no second parser of the end field's grammar lives here. *Weekend* and
 * *working week* tick their days in place; *Add an interval* and an × ask the server
 * for that part with the window added or taken out. What changes the hidden fields
 * marks its form `data-ls-dirty`, which the drawer reads as words written
 * (`drawer.js`).
 *
 * The editor's month (landing 5) is buttons without script, every day and every page;
 * here its grid is one tab stop that the arrow keys move across, as a date picker's is
 * (the roving tab stop of WAI-ARIA's grid): ← and → a day, ↑ and ↓ a week, Home and
 * End the week's first and last day in the month, Page Up and Page Down a month and
 * with Shift a year, onto the month before or after where a move leaves this one, as
 * far as its paging goes. A day clicked, or a page, is asked of the server as its
 * button would ask it, and put in place — the month apart from the rest beneath it,
 * whose live region stays and so says what the fields would set, not every day again —
 * the focus kept on the day or the page it was on.
 *
 * A standing entry's editor comes without its month (ADR-0150 decision 17): a page
 * lists an editor for every entry that stands, *Handled* one for each, and the month is
 * most of each one's weight. Its part is drawn empty and marked `data-ls-ask`, and as
 * the editor opens the month is asked of the server with the fields as they stand —
 * the rendering *Preview* draws without script — and put in place alone, the live
 * region beside it left as it is, since it already says what the fields would set.
 */
(function () {
    "use strict";

    // Once Cancel/Escape can close an editor, its open summary is redundant. The
    // class keeps the native summary available as the close control without JS.
    document.documentElement.classList.add("maintenance-edit-enhanced");

    function close(disclosure, reset) {
        if (!disclosure) { return; }
        if (reset) {
            disclosure.querySelectorAll("form.maintenance-editor-form").forEach(
                function (form) { form.reset(); });
            disclosure.querySelectorAll(".ack-kinds input").forEach(function (choice) {
                choice.checked = choice.defaultChecked;
            });
        }
        disclosure.open = false;
        var summary = disclosure.querySelector(":scope > summary");
        if (summary) { summary.focus(); }
    }

    document.addEventListener("click", function (event) {
        var cancel = event.target.closest
            ? event.target.closest(".maintenance-editor-cancel") : null;
        if (!cancel) { return; }
        event.preventDefault();
        close(cancel.closest("details"), true);
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") { return; }
        // the editor's own disclosure, so that no other the page may hold closes
        var disclosure = event.target.closest
            ? event.target.closest("details.maintenance-editor-disclosure[open]")
            : null;
        if (!disclosure) { return; }
        event.preventDefault();
        close(disclosure, true);
    });

    // An editor opens in its note: the expiry is selected only when its own
    // field takes focus (below), so the first keystroke meant for the note lands
    // in the note — at its end, since a note is added to more often than it is
    // begun again, and a field filled from markup would take the cursor at its
    // start.  `toggle` does not bubble, hence the capture.
    document.addEventListener("toggle", function (event) {
        var disclosure = event.target;
        if (!disclosure.open || !disclosure.matches
                || !disclosure.matches("details.maintenance-editor-disclosure")) {
            return;
        }
        var note = shownNote(disclosure);
        if (!note) { return; }
        note.focus();
        note.setSelectionRange(note.value.length, note.value.length);
        note.scrollTop = note.scrollHeight;
    }, true);

    // The note of the form in view: the first one drawn, where an editor holds one
    // form, and the chosen kind's in the ringed check's, whose other form is hidden.
    function shownNote(disclosure) {
        var notes = disclosure.querySelectorAll('textarea[name="note"]');
        for (var i = 0; i < notes.length; i++) {
            if (notes[i].offsetParent !== null) { return notes[i]; }
        }
        return notes.length ? notes[0] : null;
    }

    // A note written in one of the ringed check's forms is the other's too — and in
    // one of the Notes tab's, every other kind's, a note's own words `text`.
    var WORDS = '.ack-choice textarea[name="note"], .ack-choice textarea[name="text"]';

    document.addEventListener("input", function (event) {
        var note = event.target;
        if (!note.matches || !note.matches(WORDS)) { return; }
        note.closest(".ack-choice").querySelectorAll(WORDS).forEach(
            function (other) { if (other !== note) { other.value = note.value; } });
    });

    // The part chosen under the Notes tab's *On* is the other kinds' choice too,
    // where they may be set on it: a line a note was being written on is the line a
    // seen marks, once the kind changes.
    document.addEventListener("change", function (event) {
        var on = event.target;
        if (!on.matches || !on.matches('.ack-choice select[name="slug"]')) { return; }
        on.closest(".ack-choice").querySelectorAll('select[name="slug"]').forEach(
            function (other) {
                if (other === on) { return; }
                for (var i = 0; i < other.options.length; i++) {
                    if (other.options[i].value === on.value) {
                        other.selectedIndex = i;
                        return;
                    }
                }
            });
    });

    // A change of kind in the ringed check's editor moves the focus to the note of
    // the form it brings into view, as the editor's opening does.
    document.addEventListener("change", function (event) {
        var choice = event.target;
        if (!choice.matches || !choice.matches(".ack-kinds input")) { return; }
        var form = choice.closest(".ack-choice").querySelector(
            '.ack-form[data-kind="' + choice.value + '"]');
        var note = form ? form.querySelector('textarea[name="note"], textarea[name="text"]') : null;
        if (note && note.offsetParent !== null) {
            note.focus();
            note.setSelectionRange(note.value.length, note.value.length);
        }
    });

    // An edit's expiry field is filled with the expiry it keeps (ADR-0104
    // decision 5), and the form says what it was filled with — a silence's deadline
    // the same way (ADR-0144).  While the field still reads that, taking focus
    // selects it, so one keystroke replaces it and Backspace alone asks for the
    // default; once changed it is somebody's text, and the caret stays where they
    // put it.  The selection is made after the click that gave focus has placed its
    // caret, and the mouseup of that click is kept from dropping it again.
    var KEPT = { duration: "expiry_was", deadline: "deadline_was" };

    function keptExpiry(field) {
        if (!field || !KEPT.hasOwnProperty(field.name) || !field.form) { return false; }
        var was = field.form.elements.namedItem(KEPT[field.name]);
        return !!was && was.value !== "" && field.value === was.value;
    }

    var entered = null;

    document.addEventListener("focusin", function (event) {
        var field = event.target;
        if (!keptExpiry(field)) { return; }
        entered = field;
        window.setTimeout(function () {
            if (document.activeElement === field && keptExpiry(field)) {
                field.select();
            }
        }, 0);
    });

    document.addEventListener("mouseup", function (event) {
        if (entered !== null && event.target === entered) {
            event.preventDefault();
        }
        entered = null;
    });

    // --- a maintenance entry's editor: its schedule (ADR-0150, landing 4) -----------

    var PREVIEW = ".ls-schedule-preview";
    var PICKS = { weekend: ["SA", "SU"], week: ["MO", "TU", "WE", "TH", "FR"] };
    var UNITS = { daily: ["day", "days"], weekly: ["week", "weeks"],
                  monthly: ["month", "months"] };
    var WAIT_MS = 350;

    function editorOf(element) {
        var form = element && element.closest ? element.closest("form") : null;
        return form && form.querySelector(PREVIEW) ? form : null;
    }

    // A repeat, or a start typed, opens the rest in place (#35's note, decision 4).
    function openRest(form) {
        var rest = form.querySelector("details.ls-schedule-rest");
        if (!rest || rest.open) { return; }
        var repeat = form.elements.namedItem("repeat");
        var starts = form.elements.namedItem("starts");
        if ((repeat && repeat.value !== "once") ||
                (starts && starts.value.trim() !== "")) {
            rest.open = true;
        }
    }

    // *every 1 week*, *every 2 weeks*: the unit beside the count, as it is chosen —
    // and the end field's placeholder, which with a repeat asks for a length alone.
    function sayUnit(form) {
        var count = form.elements.namedItem("interval");
        var one = count && count.value.trim() === "1";
        form.querySelectorAll(".ls-every__unit [data-unit]").forEach(function (unit) {
            var words = UNITS[unit.getAttribute("data-unit")];
            if (words) { unit.textContent = words[one ? 0 : 1]; }
        });
        var repeat = form.elements.namedItem("repeat");
        var end = form.elements.namedItem("duration");
        var said = end && repeat ? end.getAttribute(
            repeat.value === "once" ? "data-once-said" : "data-length-said") : null;
        if (said !== null) { end.placeholder = said; }
    }

    // What the hidden fields carry of the windows added and left out by hand — which an
    // ×, *Add an interval* and a day of the month change — as one string to compare.
    function handmade(form) {
        var values = [];
        form.querySelectorAll('input[name="added"], input[name="extra"], ' +
                              'input[name="left_out"]').forEach(function (field) {
            values.push(field.name + "=" + field.value);
        });
        return values.sort().join("\n");
    }

    // What the fields that ask would send, as one string to compare — not the hidden
    // ones an answer fills, nor the note and *Add an interval*'s two, which ask nothing:
    // the part beneath the fields is asked again only once one of them has changed
    // since the answer in place was asked, and not for a field left (`change` after the
    // `input` that asked already).
    var QUIET = { added: 1, extra: 1, left_out: 1, month: 1, add_begins: 1,
                  add_ends: 1, note: 1 };

    function fields(form) {
        var parts = [];
        new FormData(form).forEach(function (value, name) {
            if (typeof value === "string" && !QUIET.hasOwnProperty(name)) {
                parts.push(name + "=" + value);
            }
        });
        return parts.join("&");
    }

    // An answer put in place part by part: the month, and the rest beneath it, the live
    // region, whose element stays so that what it says is read out as it changes.
    function place(region, html) {
        var fresh = document.createElement("div");
        fresh.innerHTML = html;
        var parts = [".ls-schedule-month", ".ls-schedule-said"];
        for (var i = 0; i < parts.length; i++) {
            if (!region.querySelector(parts[i]) || !fresh.querySelector(parts[i])) {
                region.innerHTML = html;
                return;
            }
        }
        parts.forEach(function (part) {
            region.querySelector(part).innerHTML = fresh.querySelector(part).innerHTML;
        });
    }

    // What an ask sends: every field as it stands but the editor's own buttons, the act
    // of the one pressed, ``extra``, where there is one, and the prefix its ids take.
    function posted(form, region, extra) {
        var data = new FormData(form);
        ["preview", "add", "drop", "pick", "day", "page"].forEach(function (name) {
            data.delete(name);
        });
        if (extra) { data.append(extra.name, extra.value); }
        data.append("prefix", region.getAttribute("data-prefix") || "form");
        return data;
    }

    // What the fields would set, asked of the server and put in place — the newest
    // answer only, a slower one that comes after it dropped, and an ask still waiting
    // dropped too, since this one sends every field as it stands. ``wanted`` is the day
    // the month's tab stop goes to, where the answer's month shows it; the focus, where
    // it was in the month, stays on its day or its page.
    function ask(form, extra, wanted) {
        var region = form.querySelector(PREVIEW);
        if (!region || !window.fetch || !window.FormData) { return; }
        if (waiting) {
            window.clearTimeout(waiting);
            waiting = null;
        }
        var data = posted(form, region, extra);
        var asked = (Number(region.getAttribute("data-asked")) || 0) + 1;
        region.setAttribute("data-asked", String(asked));
        var before = handmade(form);
        var sent = fields(form);
        var added = form.querySelectorAll('input[name="added"]').length;
        window.fetch(region.getAttribute("data-preview"), {
            method: "POST", body: data, credentials: "same-origin",
            headers: { "X-Requested-With": "fetch" }
        }).then(function (answer) {
            if (!answer.ok) { throw new Error(String(answer.status)); }
            return answer.text();
        }).then(function (html) {
            if (region.getAttribute("data-asked") !== String(asked)) { return; }
            var focused = document.activeElement;
            var inside = !!focused && region.contains(focused) &&
                focused.closest(MONTH) !== null;
            var paged = inside ? focused.getAttribute("data-page") : null;
            place(region, html);
            if (handmade(form) !== before) { form.setAttribute("data-ls-dirty", ""); }
            if (extra && extra.name === "add" &&
                    form.querySelectorAll('input[name="added"]').length > added) {
                ["add_begins", "add_ends"].forEach(function (name) {
                    var field = form.elements.namedItem(name);
                    if (field) { field.value = ""; }
                });
            }
            region.setAttribute("data-fields", sent);
            var month = region.querySelector(MONTH);
            var at = month ? rove(month, wanted) : null;
            if (!inside) { return; }
            var page = paged && month
                ? month.querySelector('.ls-cal__page[data-page="' + paged + '"]') : null;
            var target = page && !page.disabled ? page : at;
            if (target) { target.focus(); }
        }).catch(function () {
            /* nothing changes: the fields stay, and Preview or Set still sends them */
        });
    }

    var waiting = null;

    function soon(form) {
        if (waiting) { window.clearTimeout(waiting); }
        waiting = window.setTimeout(function () {
            waiting = null;
            var region = form.querySelector(PREVIEW);
            if (region && region.getAttribute("data-fields") === fields(form)) { return; }
            ask(form);
        }, WAIT_MS);
    }

    function followed(event) {
        var form = editorOf(event.target);
        if (!form) { return; }
        var name = event.target.name || "";
        if (name === "add_begins" || name === "add_ends" || name === "note") { return; }
        openRest(form);
        sayUnit(form);
        soon(form);
    }

    document.addEventListener("input", followed);
    document.addEventListener("change", followed);

    // The rest's own buttons: each does in place what it does without script — a day
    // of the month that says nothing can be done with it, nothing.
    document.addEventListener("click", function (event) {
        var button = event.target.closest
            ? event.target.closest("button[data-ls-nowrite]") : null;
        var form = button ? editorOf(button) : null;
        if (!form || !window.fetch || !window.FormData) { return; }
        event.preventDefault();
        if (button.getAttribute("aria-disabled") === "true") { return; }
        if (button.name === "day") {
            var month = button.closest(MONTH);
            if (month) { move(month, button); }
            ask(form, { name: "day", value: button.value }, button.value);
        } else if (button.name === "page") {
            ask(form, { name: "page", value: button.value });
        } else if (button.name === "pick" && PICKS[button.value]) {
            var days = PICKS[button.value];
            form.querySelectorAll('input[name="weekday"]').forEach(function (box) {
                box.checked = days.indexOf(box.value) >= 0;
            });
            ask(form);
        } else if (button.name === "add" || button.name === "drop") {
            ask(form, { name: button.name, value: button.value });
        } else {
            ask(form);
        }
    });

    // --- the editor's month (ADR-0150, landing 5) -----------------------------------

    var MONTH = ".ls-cal";
    var DAY = "button.ls-cal__day";
    var DAY_MS = 86400000;
    var MOVES = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    var PAGES = { PageUp: ["month-before", "year-before"],
                  PageDown: ["month-after", "year-after"] };

    function dateOf(value) {
        var parts = value.split("-");
        return new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1,
                                 Number(parts[2])));
    }

    function textOf(when) { return when.toISOString().slice(0, 10); }

    // The last day of ``month``, `YYYY-MM`.
    function lastOf(month) {
        return new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)),
                                 0));
    }

    // ``when``'s day of the month in ``month``, or its last day where it is shorter.
    function sameDay(when, month) {
        var last = lastOf(month);
        last.setUTCDate(Math.min(when.getUTCDate(), last.getUTCDate()));
        return textOf(last);
    }

    // The grid's one tab stop: the day ``wanted``, where the month shows it, or else
    // the day it was at, or else the one the server marks; the grid named one.
    function rove(month, wanted) {
        var days = month.querySelectorAll(DAY);
        var grid = month.querySelector(".ls-cal__grid");
        if (!days.length || !grid) { return null; }
        grid.setAttribute("role", "grid");
        var region = month.closest(PREVIEW);
        var was = region ? region.getAttribute("data-day") : null;
        var at = null, kept = null;
        days.forEach(function (day) {
            day.setAttribute("tabindex", "-1");
            if (day.value === wanted) { at = day; }
            if (day.value === was) { kept = day; }
        });
        at = at || kept || month.querySelector(DAY + "[data-focus]") || days[0];
        at.setAttribute("tabindex", "0");
        if (region) { region.setAttribute("data-day", at.value); }
        return at;
    }

    // The tab stop moved to ``day``, and the focus with it.
    function move(month, day) {
        month.querySelectorAll(DAY + '[tabindex="0"]').forEach(function (other) {
            other.setAttribute("tabindex", "-1");
        });
        day.setAttribute("tabindex", "0");
        var region = month.closest(PREVIEW);
        if (region) { region.setAttribute("data-day", day.value); }
        day.focus();
    }

    // To the day ``target``: in place where the month shows it, or else onto the month
    // ``page`` goes to — the one before or after for a move that leaves this one, where
    // its paging goes that far.
    function go(form, month, target, page) {
        var there = month.querySelector(DAY + '[value="' + target + '"]');
        if (there) {
            move(month, there);
            return;
        }
        if (!page) {
            var shown = month.getAttribute("data-month") || "";
            page = month.querySelector('.ls-cal__page[data-page="' +
                (target < shown ? "month-before" : "month-after") + '"]');
            if (!page || page.disabled || page.value !== target.slice(0, 7)) { return; }
        }
        ask(form, { name: "page", value: page.value }, target);
    }

    document.addEventListener("keydown", function (event) {
        var day = event.target.closest ? event.target.closest(DAY) : null;
        var month = day ? day.closest(MONTH) : null;
        var form = month ? editorOf(month) : null;
        if (!form || event.altKey || event.ctrlKey || event.metaKey) { return; }
        var when = dateOf(day.value);
        var target = null, page = null;
        if (MOVES.hasOwnProperty(event.key) && !event.shiftKey) {
            target = textOf(new Date(when.getTime() + MOVES[event.key] * DAY_MS));
        } else if ((event.key === "Home" || event.key === "End") && !event.shiftKey) {
            var monday = (when.getUTCDay() + 6) % 7;
            var step = event.key === "Home" ? -monday : 6 - monday;
            target = textOf(new Date(when.getTime() + step * DAY_MS));
            var shown = day.value.slice(0, 7);
            if (target.slice(0, 7) !== shown) {
                target = event.key === "Home" ? shown + "-01" : textOf(lastOf(shown));
            }
        } else if (PAGES.hasOwnProperty(event.key)) {
            page = month.querySelector('.ls-cal__page[data-page="' +
                PAGES[event.key][event.shiftKey ? 1 : 0] + '"]');
            if (page && !page.disabled) { target = sameDay(when, page.value); }
        } else {
            return;
        }
        event.preventDefault();
        if (target) { go(form, month, target, page); }
    });

    // A day that takes the focus by a click, or a grid the script has not seen — one a
    // refresh of the page put in place — takes the tab stop there.
    document.addEventListener("focusin", function (event) {
        var day = event.target.closest ? event.target.closest(DAY) : null;
        var month = day ? day.closest(MONTH) : null;
        if (!month || !editorOf(month) || day.getAttribute("tabindex") === "0") {
            return;
        }
        rove(month, day.value);
    });

    // --- a standing entry's month, asked for as its editor opens (decision 17) ------

    var ASK = ".ls-schedule-month[data-ls-ask]";
    var EDITOR = "details.maintenance-editor-disclosure";

    // The month a standing entry's editor came without, asked of the server with the
    // fields as they stand and put in place alone, its one tab stop set. Once it is
    // there — or while it is on its way — nothing is asked again; an answer to the
    // fields asked meanwhile brings a month of its own, and this one is dropped.
    function askMonth(form) {
        var region = form.querySelector(PREVIEW);
        var part = region ? region.querySelector(ASK) : null;
        if (!part || part.querySelector(MONTH) || part.hasAttribute("data-ls-asking") ||
                !window.fetch || !window.FormData) {
            return;
        }
        part.setAttribute("data-ls-asking", "");
        var asked = region.getAttribute("data-asked");
        window.fetch(region.getAttribute("data-preview"), {
            method: "POST", body: posted(form, region), credentials: "same-origin",
            headers: { "X-Requested-With": "fetch" }
        }).then(function (answer) {
            if (!answer.ok) { throw new Error(String(answer.status)); }
            return answer.text();
        }).then(function (html) {
            part.removeAttribute("data-ls-asking");
            if (region.getAttribute("data-asked") !== asked) { return; }
            var fresh = document.createElement("div");
            fresh.innerHTML = html;
            var month = fresh.querySelector(".ls-schedule-month");
            if (!month) { return; }
            part.innerHTML = month.innerHTML;
            var grid = part.querySelector(MONTH);
            if (grid) { rove(grid, null); }
        }).catch(function () {
            /* no month: the next opening asks again, and Preview still draws it */
            part.removeAttribute("data-ls-asking");
        });
    }

    function opened(disclosure) {
        disclosure.querySelectorAll(PREVIEW).forEach(function (region) {
            var form = editorOf(region);
            if (form) { askMonth(form); }
        });
    }

    // `toggle` does not bubble, hence the capture.
    document.addEventListener("toggle", function (event) {
        var disclosure = event.target;
        if (disclosure.open && disclosure.matches && disclosure.matches(EDITOR)) {
            opened(disclosure);
        }
    }, true);

    // An editor drawn with the rest open says what it would set at once, and its month
    // is one tab stop; one drawn open — the drawer's at its pin — asks for the month it
    // came without.
    document.querySelectorAll(PREVIEW).forEach(function (region) {
        var form = editorOf(region);
        if (form) {
            sayUnit(form);
            if (window.FormData) { region.setAttribute("data-fields", fields(form)); }
        }
        var month = region.querySelector(MONTH);
        if (month) { rove(month, null); }
    });
    document.querySelectorAll(EDITOR + "[open]").forEach(opened);
})();
