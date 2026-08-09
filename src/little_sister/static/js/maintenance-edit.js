/* Read-to-edit maintenance disclosures (ADR-0014 amendment).
 *
 * The disclosure itself is native <details>, so every node/entry form remains
 * usable without JavaScript.  This small enhancement gives the explicit Cancel
 * button and Escape the same meaning: reset the raw Markdown/duration fields,
 * return to rendered read mode, and put focus back on the control that opened it.
 * Only one per-reason overlay stays open at a time so a long member page cannot
 * accumulate a stack of editors.
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
        var disclosure = event.target.closest
            ? event.target.closest("details[open]") : null;
        if (!disclosure) { return; }
        event.preventDefault();
        close(disclosure, true);
    });

    document.querySelectorAll("details.reason-pin").forEach(function (disclosure) {
        disclosure.addEventListener("toggle", function () {
            if (!disclosure.open) { return; }
            document.querySelectorAll("details.reason-pin[open]").forEach(
                function (other) {
                    if (other !== disclosure) { other.open = false; }
                });
        });
    });
})();
