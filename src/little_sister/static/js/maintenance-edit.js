/* Read-to-edit maintenance disclosures (ADR-0014, ADR-0104).
 *
 * The disclosure itself is native <details>, so every node/entry form remains
 * usable without JavaScript.  This small enhancement gives the explicit Cancel
 * button and Escape the same meaning: reset the raw Markdown/duration fields,
 * return to rendered read mode, and put focus back on the control that opened it.
 * Only one line's set-editor stays open at a time so a long member page cannot
 * accumulate a stack of them.  An editor opens in its note, at the note's end,
 * and an expiry field that is still as it was filled is selected when it takes
 * focus.
 */
(function () {
    "use strict";

    // Once Cancel/Escape can close an editor, its open summary is redundant. The
    // class keeps the native summary available as the close control without JS.
    document.documentElement.classList.add("maintenance-edit-enhanced");

    function close(disclosure, reset) {
        if (!disclosure) { return; }
        if (reset) {
            var form = disclosure.querySelector("form.maintenance-editor-form");
            if (form) { form.reset(); }
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
            ? event.target.closest(
                "details.maintenance-editor-disclosure[open], details.reason-pin[open], "
                + "details.reason-ack[open]")
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
        if (!disclosure.open || !disclosure.matches || !disclosure.matches(
                "details.maintenance-editor-disclosure, details.reason-pin, details.reason-ack")) {
            return;
        }
        var note = disclosure.querySelector('textarea[name="note"]');
        if (!note) { return; }
        note.focus();
        note.setSelectionRange(note.value.length, note.value.length);
        note.scrollTop = note.scrollHeight;
    }, true);

    // An edit's expiry field is filled with the expiry it keeps (ADR-0104
    // decision 5), and the form says what it was filled with.  While the field
    // still reads that, taking focus selects it, so one keystroke replaces it and
    // Backspace alone asks for the default; once changed it is somebody's text,
    // and the caret stays where they put it.  The selection is made after the
    // click that gave focus has placed its caret, and the mouseup of that click
    // is kept from dropping it again.
    function keptExpiry(field) {
        if (!field || field.name !== "duration" || !field.form) { return false; }
        var was = field.form.elements.namedItem("expiry_was");
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

    document.querySelectorAll("details.reason-pin, details.reason-ack").forEach(function (disclosure) {
        disclosure.addEventListener("toggle", function () {
            if (!disclosure.open) { return; }
            document.querySelectorAll("details.reason-pin[open], details.reason-ack[open]").forEach(
                function (other) {
                    if (other !== disclosure) { other.open = false; }
                });
        });
    });
})();
