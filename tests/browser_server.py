"""The server a browser test serves its pages from (``testing-the-gui.md``, Mode 5).

``wsgiref``'s server answers one request at a time, and the connections that arrive
meanwhile wait in its socket's listen queue, which ``socketserver`` makes five long. A
page is a burst of them — its stylesheets and scripts, more than a dozen on a node's
page, six at a time — and a server slowed by the gate's coverage is still on the first
when the rest arrive. Linux holds a connection that finds the queue full until there is
room; macOS resets it (``net::ERR_CONNECTION_RESET``), and the page loads without that
file: a script that never ran, and a test that waits thirty seconds for what the script
would have done — on a Mac and not in a sandbox, and in a different test each run. So
the queue is as long as the platform allows, and every page a browser test opens is
served from here.
"""
from __future__ import annotations

import socket
from wsgiref.simple_server import WSGIServer


class PageServer(WSGIServer):
    """``wsgiref``'s server, with a listen queue a page's burst of connections fits."""

    request_queue_size = socket.SOMAXCONN
