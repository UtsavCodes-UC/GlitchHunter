"""Loaded automatically by Python (via PYTHONPATH) ONLY in the test copy of an uploaded app started by GlitchHunter.
If GH_RACE_PAUSE_MS is set, every SELECT sleeps that long afterwards. This widens the gap between "read" and "write" so a race
condition shows up reliably (the same idea as the demo apps' X-Race-Delay hook) without editing the user's code. It does not change
what any query returns.
Covers: psycopg2 (cursor level), synchronous SQLAlchemy engines (after_cursor_execute) and asyncpg (a non-blocking asyncio.sleep after
fetch / fetchrow / fetchval). Does NOT cover SQLAlchemy async or psycopg3 async."""
import os
import time

_ms = int(os.environ.get("GH_RACE_PAUSE_MS", "0") or 0)


def _is_select(query):
    if isinstance(query, bytes):
        query = query.decode(errors="ignore")
    return isinstance(query, str) and query.lstrip().lower().startswith("select")


if _ms > 0:
    _PausingCursor = None
    try:
        import psycopg2
        import psycopg2.extensions as _ext

        class _PausingCursor(_ext.cursor):
            def execute(self, query, vars=None):
                result = super().execute(query, vars)
                if _is_select(query):
                    time.sleep(_ms / 1000)
                return result

        _orig_connect = psycopg2.connect

        def _connect(*args, **kwargs):
            kwargs.setdefault("cursor_factory", _PausingCursor)
            return _orig_connect(*args, **kwargs)

        psycopg2.connect = _connect

        # Many apps pass cursor_factory=RealDictCursor (or DictCursor / NamedTupleCursor) to conn.cursor(), which bypasses the
        # connection default above. Those classes are written in Python, so wrap their execute() as well.
        try:
            import psycopg2.extras as _extras

            def _wrap(cls):
                orig = cls.execute

                def execute(self, query, vars=None):
                    result = orig(self, query, vars)
                    if _is_select(query):
                        time.sleep(_ms / 1000)
                    return result

                cls.execute = execute

            for _name in ("DictCursor", "RealDictCursor", "NamedTupleCursor"):
                if hasattr(_extras, _name):
                    _wrap(getattr(_extras, _name))
        except ImportError:
            pass
    except ImportError:
        pass

    try:
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, "after_cursor_execute")
        def _pause_after_select(conn, cursor, statement, parameters, context, executemany):
            # when the DBAPI cursor is already our pausing psycopg2 cursor, the pause has happened: do not sleep twice
            if _PausingCursor is not None and isinstance(cursor, _PausingCursor):
                return
            if _is_select(statement):
                time.sleep(_ms / 1000)
    except ImportError:
        pass

    # asyncpg (async): a time.sleep here would freeze the whole event loop and HIDE the race, but `await asyncio.sleep` only suspends
    # this request, so other requests run in the gap: exactly the read-check-write window we want to widen.
    try:
        import asyncio, functools
        from asyncpg import Connection as _AsyncpgConnection

        def _async_pause(orig):
            @functools.wraps(orig)
            async def wrapper(self, query, *args, **kwargs):
                result = await orig(self, query, *args, **kwargs)
                if _is_select(query):
                    await asyncio.sleep(_ms / 1000)
                return result
            return wrapper

        for _name in ("fetch", "fetchrow", "fetchval"):
            setattr(_AsyncpgConnection, _name, _async_pause(getattr(_AsyncpgConnection, _name)))
    except ImportError:
        pass
