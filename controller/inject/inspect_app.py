"""Run INSIDE an uploaded project (cwd = the project's src folder): import the FastAPI app and report what it really serves.
usage: python inspect_app.py MODULE VAR
Prints ONE line starting with GH_INSPECT_JSON: (routes with their source file and line, plus the OpenAPI document) or
GH_INSPECT_ERROR: (what went wrong while importing). Importing the app runs the user's code, exactly as starting it would."""
import importlib
import inspect
import json
import os
import sys
import traceback

sys.path.insert(0, os.getcwd())


def iter_routes(app):
    """every served route, flattened. Newer FastAPI nests included routers (_IncludedRouter) and offers iter_route_contexts();
    older versions put every APIRoute directly in app.routes (or inside a mounted router's .routes)."""
    import fastapi.routing as fr

    it = getattr(fr, "iter_route_contexts", None)
    if it is not None:
        try:
            yield from list(it(app.routes))
            return
        except Exception:
            pass

    def walk(routes):
        for r in routes:
            if isinstance(r, fr.APIRoute):
                yield r
            else:
                sub = getattr(r, "routes", None)
                if sub is not None:
                    yield from walk(sub)

    yield from walk(app.routes)


def main(module, var):
    try:
        mod = importlib.import_module(module)
        app = getattr(mod, var)
        if not hasattr(app, "routes") and callable(app):  # an app factory such as create_app()
            app = app()

        routes = []
        for r in iter_routes(app):
            if not getattr(r, "endpoint", None) or not getattr(r, "methods", None):
                continue
            fn = inspect.unwrap(r.endpoint)
            try:
                file = inspect.getsourcefile(fn) or ""
                lineno = fn.__code__.co_firstlineno
            except Exception:
                file, lineno = "", 0
            routes.append({
                "path": getattr(r, "path_format", r.path),
                "methods": sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS")),
                "name": r.name,
                "func": getattr(fn, "__name__", r.name),
                "file": os.path.abspath(file) if file else "",
                "lineno": lineno,
                "is_async": inspect.iscoroutinefunction(fn),
            })
        print("GH_INSPECT_JSON:" + json.dumps({"routes": routes, "openapi": app.openapi()}, default=str))
    except BaseException as e:  # SystemExit from a failing settings loader included
        print("GH_INSPECT_ERROR:" + json.dumps({"type": type(e).__name__, "message": str(e)[:600], "trace": traceback.format_exc()[-1800:]}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
