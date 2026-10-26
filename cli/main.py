"""GlitchHunter command line. Run from the repo root (works in the VS Code integrated terminal):
    .\\glitchhunter <command> ...        or        python -m cli <command> ...
Needs GH_DATABASE_URL (and GEMINI_API_KEY for the AI steps). Run `.\\glitchhunter doctor` first.
Exit codes: 0 = fine / no bug found / fix accepted; 1 = a bug was found / fix not accepted / test failed; 2 = setup or usage problem."""
import argparse, base64, difflib, json, os, pathlib, sys, time
import httpx, psycopg2
from controller import config, attacker, make_test, validate
from orchestrator import service, repair as rep, store, uploads, runner, llm

if hasattr(sys.stdout, "reconfigure"):  # never crash on a symbol when output is piped or the console code page is old; show progress at once
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True); sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if os.name == "nt": os.system("")  # turns on ANSI colours in older Windows consoles
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

def _c(code, s): return f"\033[{code}m{s}\033[0m" if COLOR else str(s)
green = lambda s: _c("32", s); red = lambda s: _c("31", s); yellow = lambda s: _c("33", s); bold = lambda s: _c("1", s); dim = lambda s: _c("2", s)
ASCII = bool(os.environ.get("GH_ASCII"))   # GH_ASCII=1 for plain symbols (older consoles, or output redirected in PowerShell 5.1)
OK, BAD, WARN = (green("[ok]"), red("[x]"), yellow("[!]")) if ASCII else (green("✔"), red("✖"), yellow("!"))

class CliError(Exception):
    """a problem the user can fix; printed without a traceback"""

def load(name):
    try:
        cfg = config.load(); return cfg, config.scenario(cfg, name)
    except KeyError as e: raise CliError(f"{e.args[0]}\nTip: `.\\glitchhunter scenarios` lists what is available.")

def need_app(cfg, sc):
    """make sure the app under test answers: uploaded apps are started for you, demo apps must already be running"""
    if sc.get("custom"):
        try: runner.ensure_running(cfg, sc)
        except RuntimeError as e: raise CliError(str(e))
        return
    if not runner._alive(sc["base_url"]):
        port = sc["base_url"].rsplit(":", 1)[1]; stem = pathlib.Path(sc["app_file"]).stem
        raise CliError(f"The {sc['name']} app is not running at {sc['base_url']}.\nStart it in another terminal, from the apps folder:\n"
                       f"  $env:GH_DATABASE_URL=\"postgresql://rh:rh@localhost:5432/rh\"; $env:MODE=\"vuln\"; python -m uvicorn {stem}:app --port {port}")

def rules_for(sc):
    try: inv, human = service.invariants_for_run(sc)
    except service.NoChecks as e: raise CliError(str(e) + "\nRun: .\\glitchhunter checks " + sc["name"] + " --propose --filter --auto-approve")
    return inv, human

def short(i): return i.split(".", 1)[-1]

def english_of(sc_name):
    return {i["id"]: (i.get("english") or short(i["id"])) for i in store.load_invariants(sc_name)}

def story(trial):
    custom = "initial_tables" in trial   # uploaded project: whole tables before and after
    key = next((k for k, v in trial["initial_state"].items() if v is not None), "value")
    initial, final = trial["initial_state"].get(key), trial["final_state"].get(key)
    out = [f"    Before: {json.dumps(trial['initial_tables'], default=str)[:300]}" if custom else f"    Before: {key} = {initial}"]
    taken, approved = 0, 0
    for r in trial["requests"]:
        ok = 200 <= r["status"] < 300
        if ok:
            approved += 1; taken += int(next(iter(r["params"].values()), 0)) if r["params"] else 0
        params = json.dumps(r["params"]) if r["params"] else ""
        out.append(f"    Person {chr(65 + r['req'])}  {r['method']} {r['path']} {params}  ->  " + (green("approved") if ok else red(f"refused (HTTP {r['status']})")))
    out.append(f"    After:  {json.dumps(trial['final_tables'], default=str)[:300]}" if custom else f"    After:  {key} = {final}")
    if approved > 1 and isinstance(initial, (int, float)) and taken > initial:
        out.append(red(f"    {taken} was taken in total, but only {initial} existed. The app should have refused some requests."))
    else: out.append(red("    A check failed: the data after these requests does not add up with what the requests did."))
    return "\n".join(out)

def group_checks(invs):
    groups = {}
    for i in invs:
        s = i["stats"]; groups.setdefault((s.get("sequential_fires"), s.get("concurrent_fires"), s.get("concurrent_trials"), s.get("races_observed")), []).append(i)
    return [sorted(g, key=lambda i: len(i.get("english") or i["id"])) for g in groups.values()]

# ------------------------------------------------------------------ commands
def cmd_doctor(a):
    bad = 0
    def line(ok, text, required=True):
        nonlocal bad
        print(f"  {OK if ok else (BAD if required else WARN)} {text}"); bad += (not ok and required)
    print(bold("GlitchHunter doctor"))
    line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}")
    try:
        cfg = config.load()
        try:
            c = attacker.connect(cfg)
            with c.cursor() as cur: cur.execute("show server_version"); v = cur.fetchone()[0]
            c.close(); line(True, f"PostgreSQL {v} reachable")
            try:
                a = psycopg2.connect(config.admin_url(cfg)); k = a.cursor(); k.execute("select rolcreaterole or rolsuper from pg_roles where rolname = current_user"); can = k.fetchone()[0]; a.close()
                line(can, "the database user can create roles (needed for your own code)" if can else "the database user cannot create roles, so uploaded code cannot be isolated. As a superuser run: ALTER ROLE <user> CREATEROLE;", required=False)
            except Exception: pass
        except RuntimeError as e: line(False, f"{e}. Set it with: $env:GH_DATABASE_URL=\"postgresql://rh:rh@localhost:5432/rh\"")
        except Exception as e: line(False, f"cannot connect to PostgreSQL: {str(e).strip().splitlines()[0]}")
    except Exception as e: line(False, f"cannot read the config: {e}"); cfg = None
    gemini = bool(os.environ.get("GEMINI_API_KEY"))
    line(gemini or llm.PROVIDER != "gemini", f"LLM provider {llm.PROVIDER}, model {llm.MODEL}" + (", GEMINI_API_KEY is set" if gemini else ", GEMINI_API_KEY is NOT set (Ollama fallback will be used)"), required=False)
    try:
        models = [m["name"] for m in httpx.get(f"{llm.OLLAMA_URL}/api/tags", timeout=3).json()["models"]]
        line(True, f"Ollama fallback available ({', '.join(models)})", required=False)
    except Exception: line(False, "Ollama is not running (no fallback if Gemini's quota runs out; start it with `ollama serve`)", required=False)
    if cfg:
        for name, sc in cfg["scenarios"].items():
            if sc.get("custom"): print(f"  {dim('-')} {name}: uploaded app, started on demand"); continue
            line(runner._alive(sc["base_url"]), f"{name} app at {sc['base_url']}" + ("" if runner._alive(sc["base_url"]) else " is not running (see apps/README.md)"), required=False)
    print(bold("Ready." if not bad else red("Fix the ✖ items above first.")))
    return 1 if bad else 0

def cmd_scenarios(a):
    cfg = config.load()
    print(bold(f"{'ID':32s} {'KIND':9s} ENDPOINT"))
    for name, sc in cfg["scenarios"].items():
        ep = sc["endpoint"]; print(f"{name:32s} {'uploaded' if sc.get('custom') else 'demo':9s} {ep['method']} {ep['path']} {json.dumps(ep['params'])}  ({sc.get('race_n', 2)} at once)")
    return 0

def cmd_scan(a):
    cfg, sc = load(a.scenario); need_app(cfg, sc); inv, human = rules_for(sc)
    n = a.n or sc["race_n"]; ep = sc["endpoint"]
    if not a.json:
        print(bold(f"Scan: {sc['name']}") + dim(f"   {ep['method']} {ep['path']} {json.dumps(ep['params'])}, {n} simultaneous requests x {a.trials} tries"))
        print(f"  Using {len(inv)} {'approved' if human else 'built-in'} check(s)" + ("" if human else yellow("  (no check approved yet: using the built-in one)")))
    run_id = f"cli_{sc['name']}_{int(time.time())}"
    summary, failing = attacker.attack(cfg, sc, inv, a.trials, n, a.delay, run_id)
    bad = summary["trials_with_violation"]
    if a.json:
        print(json.dumps({"summary": summary, "first_failing_trial": failing[0] if failing else None}, indent=2, default=str)); return 1 if bad else 0
    print(("  " + red(f"Went wrong in {bad} of {a.trials} tries.")) if bad else ("  " + green(f"No problem found in {a.trials} tries.") + dim(" (a race can be rare: try more --trials)")))
    if bad:
        eng = english_of(sc["name"])
        print("  Checks that broke:")
        same = {}
        for k, v in summary["per_invariant"].items():
            if v: same.setdefault(v, []).append(k)   # checks with identical results are shown once
        for v, ks in same.items():
            first = min(ks, key=lambda k: len(eng.get(k, short(k))))
            print(f"    {v}x  {eng.get(first, short(first))}" + (dim(f"  (+{len(ks) - 1} more with the same result)") if len(ks) > 1 else ""))
        print("  One failed try:"); print(story(failing[0]))
        print(dim(f"  Saved replayable run: runs/{run_id}/failing_trial_{failing[0]['trial']:03d}.json"))
        print(dim(f"  Next: .\\glitchhunter repair {sc['name']}"))
    return 1 if bad else 0

def cmd_checks(a):
    cfg, sc = load(a.scenario)
    if a.propose or a.filter: need_app(cfg, sc)
    if a.propose:
        print(dim("Asking the AI for checks (usually under a minute)..."))
        invs, stats = service.propose(cfg, sc, a.samples)
        print(f"  {stats['unique_valid']} usable suggestions from {stats['model']} ({stats['valid_sql']} of {stats['proposed']} had valid SQL)")
        if str(stats["model"]).startswith("ollama:"): print(yellow("  ! The Gemini models were unavailable, so the local Ollama model answered (weaker)."))
    if a.filter:
        print(dim("Testing each check on one-at-a-time and simultaneous runs..."))
        service.run_filter(cfg, sc, a.decoys)
    invs = store.load_invariants(sc["name"])
    for tok in a.approve or []:
        hit = [i for i in invs if tok in i["id"]]
        if not hit: raise CliError(f"no check matches '{tok}'. Run `.\\glitchhunter checks {sc['name']}` to see the ids.")
        for i in hit: store.set_status(sc["name"], i["id"], "approved")
    for tok in a.reject or []:
        for i in [i for i in invs if tok in i["id"]]: store.set_status(sc["name"], i["id"], "rejected")
    if a.auto_approve:
        for i in invs:
            if i["status"] == "proposed" and i["stats"].get("concurrent_fires"): store.set_status(sc["name"], i["id"], "approved")
    invs = store.load_invariants(sc["name"])
    if a.json: print(json.dumps(invs, indent=2, default=str)); return 0
    if not invs: print(yellow("No checks yet. Run: .\\glitchhunter checks " + sc["name"] + " --propose --filter")); return 0
    usable = [i for i in invs if i["status"] in ("proposed", "approved", "rejected") and i["stats"].get("concurrent_fires")]
    print(bold(f"Checks for {sc['name']}"))
    for g in group_checks(usable):
        i = g[0]; st = i["stats"]; status = "approved" if any(x["status"] == "approved" for x in g) else ("skipped" if all(x["status"] == "rejected" for x in g) else "suggested")
        mark = green("USING  ") if status == "approved" else (dim("SKIPPED") if status == "skipped" else yellow("NEW    "))
        print(f"  {mark} {(i.get('english') or short(i['id']))[:96]}")
        print(dim(f"          id: {short(i['id'])}" + (f"  (+{len(g)-1} more worded differently)" if len(g) > 1 else "") + f" | quiet on {st['sequential_trials']-st['sequential_fires']}/{st['sequential_trials']} normal runs, alarm on {st['concurrent_fires']}/{st['concurrent_trials']} simultaneous runs | {i['source']}"))
    thrown = [i for i in invs if i["status"] in ("dropped", "uninformative")]
    if thrown: print(dim(f"  {len(thrown)} suggestion(s) thrown out by the filter (wrong on normal runs, or never raise the alarm)."))
    sel = sum(1 for g in group_checks(usable) if any(x["status"] == "approved" for x in g))
    print(f"  {sel} selected." + ("" if sel else yellow(f"  Approve one: .\\glitchhunter checks {sc['name']} --approve <id>   (or --auto-approve)")))
    return 0

def cmd_repair(a):
    cfg, sc = load(a.scenario); need_app(cfg, sc); inv, human = rules_for(sc)
    print(bold(f"Repair: {sc['name']}") + dim(f"   {len(inv)} {'approved' if human else 'built-in'} check(s); the AI writes a fix, we test it on a copy (1 to 3 minutes)"))
    try: res = rep.repair(cfg, sc, inv, a.k, a.attempts)
    except RuntimeError as e: raise CliError(str(e))
    a.result = res   # for `fix`, which applies the accepted patch
    if a.json: print(json.dumps(res, indent=2, default=str)); return 0 if res["accepted"] else 1
    for t in res["attempts"]:
        head = f"  Attempt {t['attempt']}: {t.get('strategy') or '(no strategy)'}" + dim(f"  [{t.get('model', '?')}]")
        print(head + "  " + (green("ACCEPTED") if t["accepted"] else red("REJECTED")))
        if t["accepted"]:
            v = t["validation"]
            print(f"    {OK} everyday behaviour unchanged" if not v["regression_failures"] else f"    {BAD} everyday behaviour changed")
            print(f"    {OK} the failing situation no longer breaks")
            for f in v.get("fresh_trials", []): print(f"    {OK if not f['violations'] else BAD} {f['trials']} fresh simultaneous tries" + (f" with a {f['delay_ms']} ms pause" if f["delay_ms"] and not sc.get("custom") else "") + f": {f['violations']} went wrong")
            if "throughput_rps" in v: print(dim(f"    speed: about {v['throughput_rps']} requests per second (one noisy measurement)"))
        else: print(dim(f"    why: {t.get('reason', '')[:200]}"))
        if t.get("explanation") and t["accepted"]: print(dim(f"    {t['explanation'][:200]}"))
    nc = res["negative_control"]
    print(f"  {OK if nc['validator_working'] else BAD} control: the ORIGINAL buggy code was " + ("rejected by the same tests, as it should be." if nc["validator_working"] else red("ACCEPTED, so do not trust the verdict!")))
    if res["accepted"]:
        acc = next(t for t in res["attempts"] if t["accepted"]); out = config.ROOT / "runs" / "patches"; out.mkdir(parents=True, exist_ok=True)
        p = out / f"{sc['name']}_{int(time.time())}.py"; p.write_text(acc["patch"]["code"] + "\n", encoding="utf-8")
        print(green(bold("  A fix was found and it passed every test.")) + dim("  (evidence, not a proof)"))
        print(f"  Fixed function saved to {p}" + ("" if getattr(a, "from_fix", False) else dim("  (your files are never edited; copy it in)")))
        if a.code: print("\n" + acc["patch"]["code"])
    else: print(red(bold("  No safe fix was found in these attempts.")))
    return 0 if res["accepted"] else 1

def cmd_replay(a):
    f = pathlib.Path(a.file)
    if not f.exists(): raise CliError(f"file not found: {f}")
    trial = json.loads(f.read_text(encoding="utf-8")); cfg, sc = load(trial["scenario"]); need_app(cfg, sc); inv, _ = rules_for(sc)
    print(bold(f"Replay: {f.name}") + dim(f"   {trial['n']} simultaneous requests, {trial.get('delay_ms', 0)} ms pause, {a.trials} times"))
    summary, failing = attacker.attack(cfg, sc, inv, a.trials, trial["n"], trial.get("delay_ms", 0), f"replay_{int(time.time())}", save=False)
    bad = summary["trials_with_violation"]
    print("  " + (red(f"The problem happened again in {bad} of {a.trials} replays.") if bad else green(f"No problem in {a.trials} replays (it is not present now).")))
    return 1 if bad else 0

def cmd_test(a):
    cfg, sc = load(a.scenario)
    if sc.get("custom"): raise CliError("test generation currently supports the demo scenarios (wallet, inventory) only.")
    need_app(cfg, sc); inv, _ = rules_for(sc)
    print(dim("Looking for a failing run to turn into a test..."))
    _, failing = attacker.attack(cfg, sc, inv, 20, delay=30, run_id=f"maketest_{sc['name']}", save=False)
    if not failing: raise CliError("no failing run found: is the app running in MODE=vuln?")
    p = make_test.generate(sc, failing[0], f"a live attack on {sc['base_url']}")
    print(green(f"  Wrote {p}"))
    print(dim(f"  Run it:  python {p.relative_to(config.ROOT)}          (red on the buggy app, green on a fixed one)"))
    print(dim(f"  Other app:  $env:GH_TARGET_URL=\"http://127.0.0.1:8010\"; python {p.relative_to(config.ROOT)}"))
    return 0

def _gather(path):
    """(relative path, bytes) pairs from a .zip, a single file or a folder (venv, .git, node_modules and other skipped folders are filtered by the server rules)"""
    p = pathlib.Path(path)
    if not p.exists(): raise CliError(f"not found: {p}")
    if p.is_file(): return [(p.name, p.read_bytes())]
    return [(f.relative_to(p).as_posix(), f.read_bytes()) for f in sorted(p.rglob("*")) if f.is_file() and not (set(f.relative_to(p).parts[:-1]) & uploads.SKIP_DIRS)
            and f.suffix.lower() in uploads.TEXT_EXT and f.stat().st_size <= uploads.LIMITS()["file"]]

def _print_scan(m):
    sc = m["scan"]; mark = {"suspect": red, "guarded": green, "writes": yellow, "read-only": dim}
    print(bold(f"Project {m['id']}  \"{m['name']}\": {m['endpoints']} endpoint(s), {m['risky']} suspect  ({m['status']})") + dim("   (static scan: nothing was run)"))
    for w in sc["warnings"]: print(yellow("  ! " + w))
    for r in sc["routes"]: print(f"  {mark[r['verdict']](r['verdict']):20s} {r['method']:6s} {r['path']}  {dim(r['reasons'][0])}")

def cmd_upload(a):
    cfg = config.load()
    name = a.name or pathlib.Path(a.path).resolve().stem   # a folder or zip is named after itself, not after something inside it
    try: m = uploads.create(cfg, name, _gather(a.path))
    except ValueError as e: raise CliError(str(e))
    _print_scan(m)
    print(dim(f"  Next: .\\glitchhunter setup {m['id']}      (uses the suggested setup; or --config setup.json)"))
    return 0

def cmd_setup(a):
    cfg = config.load()
    try: meta = uploads.get(a.project)
    except KeyError: raise CliError(f"no such project: {a.project}")
    if a.config:
        try: raw = json.loads(pathlib.Path(a.config).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e: raise CliError(f"could not read the setup file: {e}")
    else:
        raw = meta["suggested"]
        if not raw: raise CliError("no suggested setup: give one with --config")
        print(dim("Using the suggested setup (edit it in the dashboard or pass --config)."))
    try: uploads.save_setup(a.project, raw)
    except ValueError as e: raise CliError(str(e))
    t0 = time.time()
    try: res = uploads.run_check(cfg, a.project, lambda m: print(f"  [{time.time() - t0:4.1f}s] {m}"))
    except (ValueError, RuntimeError) as e: raise CliError(str(e))
    print((green if res["verdict"] == "ok" else yellow if res["verdict"] == "warning" else red)(f"Setup test: {res['verdict']}: {res['message']}"))
    if res["verdict"] == "server error": return 1
    print(dim(f"  Next: .\\glitchhunter checks {a.project} --propose --filter --auto-approve   then   scan {a.project}   then   repair {a.project}"))
    return 0

def _need_database(cfg):
    try: attacker.connect(cfg).close()
    except RuntimeError as e: raise CliError(f"{e}.\nSet it first (PowerShell):  $env:GH_DATABASE_URL=\"postgresql://rh:rh@localhost:5432/rh\"")
    except Exception as e: raise CliError(f"cannot connect to PostgreSQL: {str(e).strip().splitlines()[0]}")

def _step(n, total, text): print(bold(f"[{n}/{total}] {text}"))

def cmd_fix(a):
    """one command for the whole loop on a project folder: read, set up, test the setup, find checks, attack, repair, optionally write the fix back"""
    cfg = config.load(); root = pathlib.Path(a.path).resolve(); ns = argparse.Namespace
    if not root.exists(): raise CliError(f"not found: {root}")
    _need_database(cfg)
    base = root.parent if root.is_file() else root
    cfg_file = pathlib.Path(a.config) if a.config else (base / "glitchhunter.json" if (base / "glitchhunter.json").exists() else None)
    _step(1, 6, f"Reading {root.name} (nothing is run)")
    try: meta = uploads.create(cfg, a.name or root.stem, _gather(root))
    except ValueError as e: raise CliError(str(e))
    pid = meta["id"]; _print_scan(meta)
    try:
        if cfg_file:
            try: raw = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e: raise CliError(f"could not read {cfg_file}: {e}")
            print(dim(f"  Using the setup in {cfg_file}"))
        else:
            full = uploads.get(pid); raw = full["suggested"]
            if a.endpoint:
                m, _, path = a.endpoint.partition(" ")
                r = next((x for x in full["scan"]["routes"] if x["method"] == m.upper() and x["path"] == path.strip() and x["app"]), None)
                if not r: raise CliError(f"endpoint '{a.endpoint}' was not found; pick one of the listed ones.")
                raw = {**(raw or {}), "app": r["app"], "file": r["file"], "func": r["function"], "method": r["method"], "path": r["path"], "body": "json" if r["body"] else "query",
                       "burst": [dict(r["sample"]) for _ in range(4)], "schema_sql": full["scan"]["schema_sql"], "seed_sql": full["scan"]["seed_sql"],
                       "db_env": full["scan"]["db_env"]["guess"], "env": full["scan"]["db_env"]["env"]}
            if not raw: raise CliError("no endpoint was found to attack.")
            if not raw.get("schema_sql", "").strip() and not raw.get("seed_sql", "").strip():
                raise CliError("The scan could not work out your tables or starting rows, so it cannot set the app up by itself.\n"
                               "Create a glitchhunter.json next to your code (or pass --config FILE) like this, then run the command again:\n" + json.dumps(raw, indent=2)
                               + "\nFill in schema_sql (CREATE TABLE ...) and seed_sql (INSERT ... with a small stock, such as 1). Leave schema_sql empty if the app creates its own tables.")
            print(dim(f"  No glitchhunter.json: using the suggested setup for {raw['method']} {raw['path']}"))
        _step(2, 6, "Saving the setup and testing it once in isolation")
        try: uploads.save_setup(pid, raw)
        except ValueError as e: raise CliError(str(e))
        t0 = time.time()
        res = uploads.run_check(cfg, pid, lambda m: print(f"  [{time.time() - t0:4.1f}s] {m}"))
        if res["verdict"] == "server error": raise CliError(res["message"])
        _step(3, 6, "Asking the AI for checks and testing them")
        cmd_checks(ns(scenario=pid, propose=True, filter=True, samples=a.samples, decoys=False, approve=None, reject=None, auto_approve=True, json=False))
        if not store.approved(pid): raise CliError("No check survived the filter, so nothing can tell a wrong result from a right one. Try again (the AI may answer differently), or write a check by hand.")
        _step(4, 6, f"Attacking with {len(uploads.get(pid)['config']['burst'])} simultaneous requests, {a.trials} times")
        if cmd_scan(ns(scenario=pid, trials=a.trials, n=None, delay=0, json=False)) == 0: return 0
        _step(5, 6, "Asking the AI for a fix and testing it on a copy"); rargs = ns(scenario=pid, k=a.k, attempts=a.attempts, code=False, json=False, from_fix=True)
        if cmd_repair(rargs) != 0: return 1
        _, sc = load(pid); code = next(t for t in rargs.result["attempts"] if t["accepted"])["patch"]["code"]
        _step(6, 6, "The fix as a change to your file")
        meta2 = uploads.get(pid); cfgd = meta2["config"]; target = root if root.is_file() else root / (meta2.get("stripped") or "") / cfgd["file"]
        raw_bytes = target.read_bytes(); bom = raw_bytes.startswith(b"\xef\xbb\xbf"); old = raw_bytes.decode("utf-8-sig")
        new = validate.patched_source(old, sc, code)
        diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{cfgd['file']}", f"b/{cfgd['file']}"))
        print("".join((green(l) if l.startswith("+") and not l.startswith("+++") else red(l) if l.startswith("-") and not l.startswith("---") else l) for l in diff.splitlines(True)))
        out = config.ROOT / "runs" / "patches"; out.mkdir(parents=True, exist_ok=True); dp = out / f"{pid}_{int(time.time())}.diff"; dp.write_text(diff, encoding="utf-8")
        if a.apply:
            bak = target.with_name(target.name + ".glitchhunter.bak"); bak.write_bytes(raw_bytes)
            target.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
            print(green(bold(f"  Applied to {target}")) + dim(f"   (original saved as {bak.name})"))
        else: print(f"  Not applied. Diff saved to {dp}\n  To write it into your file, run again with --apply (a .glitchhunter.bak backup is kept).")
        return 0
    finally:
        if a.keep: print(dim(f"  Kept project {pid} (see it in the dashboard; remove it with: glitchhunter delete-project {pid})"))
        else:
            try: uploads.delete(cfg, pid)
            except Exception as e: print(yellow(f"  could not remove the temporary project {pid}: {e}"))

def cmd_delete(a):
    cfg = config.load()
    try: uploads.delete(cfg, a.project)
    except KeyError: raise CliError(f"no such project: {a.project}")
    print(green(f"Deleted project {a.project} (its files, database role and schema, results)")); return 0

def cmd_serve(a):
    from . import serve
    return serve.serve(a, sys.modules[__name__])

def cmd_ui(a):
    from . import serve
    return serve.run_ui(a, sys.modules[__name__])

def cmd_stop(a):
    from . import serve
    return serve.stop(a, sys.modules[__name__])

def cmd_demo(a):
    from orchestrator import gate_a
    sys.argv = ["glitchhunter demo", a.scenario, "--samples", str(a.samples), "--k", str(a.k)] + ([] if a.no_decoys else ["--decoys"])
    return 0 if gate_a.main() else 1

# ------------------------------------------------------------------ parser
def build():
    p = argparse.ArgumentParser(prog="glitchhunter", description="Find, reproduce and fix race conditions in database-backed APIs. Start with: doctor, then demo wallet.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Demo in two terminals:\n  terminal 1:  .\\glitchhunter serve      (whole backend)\n  terminal 2:  .\\glitchhunter ui         (dashboard, then open http://localhost:3000)\n\nOr use the command line only:\n  .\\glitchhunter doctor\n  .\\glitchhunter checks wallet --propose --filter --auto-approve\n  .\\glitchhunter scan wallet\n  .\\glitchhunter repair wallet\n  .\\glitchhunter test wallet\n\nExit codes: 0 fine, 1 bug found / fix not accepted, 2 setup problem.")
    p.add_argument("--debug", action="store_true", help="show Python tracebacks")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")
    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_, description=help_); s.set_defaults(func=fn); return s
    s = add("serve", cmd_serve, "START THE WHOLE BACKEND in this window (demo apps + API); Ctrl+C stops it")
    s.add_argument("--restart", action="store_true", help="first stop leftover servers on our ports"); s.add_argument("--no-fixed", action="store_true", help="do not start the fixed wallet copy (port 8010)"); s.add_argument("--no-inventory", action="store_true")
    s = add("ui", cmd_ui, "START THE DASHBOARD at http://localhost:3000 (builds it first if needed)")
    s.add_argument("--dev", action="store_true", help="development mode (hot reload) instead of the steadier production build"); s.add_argument("--restart", action="store_true", help="replace whatever is on port 3000"); s.add_argument("--rebuild", action="store_true")
    s = add("stop", cmd_stop, "stop leftover backend servers (and uploaded-app test copies)"); s.add_argument("--all", action="store_true", help="also stop the dashboard on port 3000")
    add("doctor", cmd_doctor, "check the database, AI keys and running apps")
    add("scenarios", cmd_scenarios, "list the demo and uploaded scenarios")
    s = add("scan", cmd_scan, "attack the app with simultaneous requests (exit 1 if a bug is found)")
    s.add_argument("scenario"); s.add_argument("--trials", type=int, default=50); s.add_argument("-n", type=int, help="simultaneous requests per try"); s.add_argument("--delay", type=int, default=0, help="demo apps: test pause in ms"); s.add_argument("--json", action="store_true")
    s = add("checks", cmd_checks, "AI-suggested checks: propose, filter, approve")
    s.add_argument("scenario"); s.add_argument("--propose", action="store_true"); s.add_argument("--filter", action="store_true"); s.add_argument("--samples", type=int, default=3)
    s.add_argument("--decoys", action="store_true", help="add a deliberately wrong check to show the filter works"); s.add_argument("--approve", nargs="+", metavar="ID"); s.add_argument("--reject", nargs="+", metavar="ID")
    s.add_argument("--auto-approve", action="store_true", help="approve every check that survived the filter"); s.add_argument("--json", action="store_true")
    s = add("repair", cmd_repair, "AI writes a fix; it is tested on a copy (exit 0 only if accepted)")
    s.add_argument("scenario"); s.add_argument("--k", type=int, default=50, help="fresh tries per batch"); s.add_argument("--attempts", type=int, default=3); s.add_argument("--code", action="store_true", help="print the accepted code"); s.add_argument("--json", action="store_true")
    s = add("replay", cmd_replay, "re-run a saved failing schedule (exit 1 if the problem happens again)")
    s.add_argument("file"); s.add_argument("--trials", type=int, default=20)
    s = add("test", cmd_test, "write a regression test from a failing run (demo scenarios)"); s.add_argument("scenario")
    s = add("upload", cmd_upload, "add your own code (a .zip, a folder or one .py file); it is only scanned, not run")
    s.add_argument("path"); s.add_argument("--name", help="project name (default: the folder or zip name)")
    s = add("setup", cmd_setup, "save the setup for an uploaded project and test it once in isolation")
    s.add_argument("project", help="project id, for example u1a2b3c4d5e6"); s.add_argument("--config", help="a setup JSON file (default: the suggested setup)")
    s = add("fix", cmd_fix, "ALL IN ONE: read a project folder, set it up, find the race, ask the AI for a fix, test it (--apply writes it into your file)")
    s.add_argument("path", help="the project folder, a .zip or a single .py file"); s.add_argument("--name"); s.add_argument("--config", help="setup JSON (default: glitchhunter.json in the folder, else the suggested setup)")
    s.add_argument("--endpoint", help='attack this endpoint, for example "POST /withdraw" (default: the most suspicious one)'); s.add_argument("--trials", type=int, default=30)
    s.add_argument("--k", type=int, default=30, help="fresh tries per batch when testing a fix"); s.add_argument("--attempts", type=int, default=3); s.add_argument("--samples", type=int, default=3, help="AI samples for checks")
    s.add_argument("--apply", action="store_true", help="write the accepted fix into your file (keeps a .glitchhunter.bak copy)"); s.add_argument("--keep", action="store_true", help="keep the temporary project (database role, files) afterwards")
    s = add("delete-project", cmd_delete, "remove an uploaded project: files, database role and schema, results"); s.add_argument("project", help="project id")
    s = add("demo", cmd_demo, "the whole loop in one go: propose, filter, approve, attack, repair, control")
    s.add_argument("scenario"); s.add_argument("--samples", type=int, default=3); s.add_argument("--k", type=int, default=50); s.add_argument("--no-decoys", action="store_true")
    return p

def main(argv=None):
    a = build().parse_args(argv)
    try: code = a.func(a) or 0
    except CliError as e: print(red("error: ") + str(e), file=sys.stderr); code = 2
    except RuntimeError as e: print(red("error: ") + str(e), file=sys.stderr); code = 2
    except KeyboardInterrupt: print("\ninterrupted"); code = 130
    except Exception as e:
        if a.debug: raise
        print(red("error: ") + f"{type(e).__name__}: {str(e)[:300]}\nRun again with --debug for the full traceback, or `.\\glitchhunter doctor` to check your setup.", file=sys.stderr); code = 2
    sys.exit(code)
