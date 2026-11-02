"""Android entry point: starts the existing Flask app on loopback only."""

from __future__ import annotations

import os
import threading

_server = None
_thread = None


def start_server(
    data_dir: str,
    timezone: str | None = None,
    temp_dir: str | None = None,
) -> int:
    """Configure persistent storage, import the existing app, start WSGI."""
    global _server, _thread
    if _server is not None:
        return int(_server.server_port)

    os.environ["NETPRACTICE_DATA_DIR"] = data_dir
    os.environ["NETPRACTICE_HOST"] = "127.0.0.1"
    if temp_dir:
        os.environ["TMPDIR"] = temp_dir
        os.environ["TEMP"] = temp_dir
        os.environ["TMP"] = temp_dir
        import tempfile
        tempfile.tempdir = temp_dir
    if timezone and ("/" in timezone or timezone in {"UTC", "GMT"}):
        os.environ["TZ"] = timezone
        try:
            import time
            time.tzset()
        except (AttributeError, OSError):
            # Some platforms (notably Windows) do not implement tzset().
            pass

    from werkzeug.serving import make_server
    from app import app as flask_app

    _server = make_server("127.0.0.1", 0, flask_app, threaded=True)
    _thread = threading.Thread(
        target=_server.serve_forever,
        name="netpractice-flask",
        daemon=True,
    )
    _thread.start()
    return int(_server.server_port)


def stop_server() -> None:
    global _server, _thread
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
    _thread = None
