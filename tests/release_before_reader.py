"""Read kept files as the release before reads them at its start, with that release's
own code — its tag's ``src`` (ADR-0132, the consequence on the kept file's entries).

    python -I -S release_before_reader.py <extract> <instant> <file>...

``-I -S``: neither this checkout's environment nor any site-packages is importable, so
``little_sister`` is the extract's, which the script puts first on ``sys.path`` and
checks. Each file is read as ``app.py``'s start reads it — its events, its table of
nodes and the stop's stamp, then ``restore_events`` — with the clock fixed at
``<instant>``, an ISO instant with an offset. Prints, as JSON by file name, what that
release then holds — the payload it writes back and every node's history — or why it
refused the file. Run by ``test_branch_period_kept``; it is no test itself."""
import json
import os
import sys
from datetime import datetime

extract, at, *files = sys.argv[1:]
sys.path.insert(0, extract)
from little_sister import instants  # noqa: E402
from little_sister import tree as tree_module  # noqa: E402

if not os.path.realpath(tree_module.__file__).startswith(os.path.realpath(extract)):
    sys.exit(f"little_sister.tree is not the extract's: {tree_module.__file__}")
fixed = datetime.fromisoformat(at)
instants.now = lambda: fixed  # type: ignore[assignment]
held = {}
for name in files:
    with open(name, encoding="utf-8") as kept:
        payload = json.load(kept)
    try:
        events = tree_module.events_from_payload(payload)
        nodes = tree_module.nodes_from_payload(payload)
        tree_module.stopped_at_of(payload)
        tree = tree_module.StatusTree()
        tree.restore_events(events, nodes)
    except ValueError as error:
        held[name] = {"refused": str(error)}
        continue
    paths = sorted({event.path for event in events} | set(nodes or {}))
    held[name] = {"payload": tree.events_payload(),
                  "history": {path: [repr(period) for period in tree.history(path)]
                              for path in paths}}
json.dump(held, sys.stdout, default=str)
