"""Loaded automatically by Python (via PYTHONPATH) ONLY in the test copy of an uploaded app started by GlitchHunter.
If GH_RACE_PAUSE_MS is set, every SELECT made through psycopg2 sleeps that long afterwards. This widens the gap between
"read" and "write" so a race condition shows up reliably, the same idea as the demo apps' X-Race-Delay hook, but without
editing the user's code. It does not change what any query returns. Covers psycopg2 only (not SQLAlchemy-async, psycopg3, asyncpg)."""
import os
import time

_ms = int(os.environ.get("GH_RACE_PAUSE_MS", "0") or 0)
if _ms > 0:
    try:
        import psycopg2
        import psycopg2.extensions as _ext

        class _PausingCursor(_ext.cursor):
            def execute(self, query, vars=None):
                result = super().execute(query, vars)
                if isinstance(query, (str, bytes)):
                    q = query.decode() if isinstance(query, bytes) else query
                    if q.lstrip().lower().startswith("select"):
                        time.sleep(_ms / 1000)
                return result

        _orig_connect = psycopg2.connect

        def _connect(*args, **kwargs):
            kwargs.setdefault("cursor_factory", _PausingCursor)
            return _orig_connect(*args, **kwargs)

        psycopg2.connect = _connect
    except ImportError:
        pass
