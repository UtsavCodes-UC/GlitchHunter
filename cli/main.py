"""GlitchHunter command line. Run from the repo root (works in the VS Code integrated terminal):
    .\\glitchhunter <command> ...        or        python -m cli <command> ...
Needs GH_DATABASE_URL (and GEMINI_API_KEY for the AI steps). Run `.\\glitchhunter doctor` first.
Exit codes: 0 = fine / no bug found / fix accepted; 1 = a bug was found / fix not accepted / test failed; 2 = setup or usage problem."""
import argparse, base64, json, os, pathlib, sys, time
import httpx
from controller import config, attacker, make_test
from orchestrator import service, repair as rep, store, projects, runner, llm

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
    key = next((k for k, v in trial["initial_state"].items() if v is not None), "value")
    initial, final = trial["initial_state"].get(key), trial["final_state"].get(key)
    out = [f"    Before: {key} = {initial}"]
    taken, approved = 0, 0
    for r in trial["requests"]:
        ok = r["status"] == 200
        if ok:
            approved += 1; taken += int(next(iter(r["params"].values()), 0)) if r["params"] else 0
        params = json.dumps(r["params"]) if r["params"] else ""
        out.append(f"    Person {chr(65 + r['req'])}  {r['method']} {r['path']} {params}  ->  " + (green("approved") if ok else red(f"refused (HTTP {r['status']})")))
    out.append(f"    After:  {key} = {final}")
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
        print(f"  Fixed function saved to {p}" + dim("  (your files are never edited; copy it in)"))
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

def cmd_upload(a):
    cfg = config.load(); app_f, sql_f = pathlib.Path(a.app), pathlib.Path(a.sql)
    for f in (app_f, sql_f):
        if not f.exists(): raise CliError(f"file not found: {f}")
    try: meta = projects.create(cfg, a.name, app_f.name, app_f.read_bytes(), sql_f.read_text(encoding="utf-8"), a.env)
    except ValueError as e: raise CliError(str(e))
    print(bold(f"Found your app in {meta['entry']['file']}") + f" with table(s) {', '.join(meta['tables'])}")
    for w in meta["warnings"]: print(yellow("  ! " + w))
    for e in meta["endpoints"]: print(f"  {'*' if e['supported'] else '-'} {e['method']} {e['path']}  {dim(e['hint'])}")
    ep = None
    if a.endpoint:
        m, _, p = a.endpoint.partition(" "); ep = next((e for e in meta["endpoints"] if e["method"] == m.upper() and e["path"] == p.strip()), None)
        if not ep: raise CliError(f"endpoint '{a.endpoint}' was not found; pick one of the listed ones.")
    else: ep = next((e for e in meta["endpoints"] if e["supported"]), None)
    if not ep: raise CliError("no supported endpoint found.")
    try: params = json.loads(a.params) if a.params else ep["sample_params"]
    except ValueError: raise CliError("--params must be valid JSON, for example '{\"qty\": 1}'")
    state = None
    if a.state:
        t, _, c = a.state.partition("."); state = {"table": t, "column": c}
    try: sc = projects.create_scenario(meta["id"], ep["method"], ep["path"], params, a.n, state)
    except ValueError as e: raise CliError(str(e))
    print(green(f"Created scenario {sc['id']}") + f" (attacking {ep['method']} {ep['path']} {json.dumps(params)}, {a.n} at once, watching {sc['state']['table']}.{sc['state']['column']})")
    print(dim(f"  Next: .\\glitchhunter checks {sc['id']} --propose --filter --auto-approve   then   .\\glitchhunter scan {sc['id']}   then   .\\glitchhunter repair {sc['id']}"))
    return 0

def cmd_delete(a):
    cfg = config.load()
    try: projects.delete(cfg, a.project)
    except KeyError: raise CliError(f"no such project: {a.project}")
    print(green(f"Deleted project {a.project} (its app, files and private database schema)")); return 0

def cmd_demo(a):
    from orchestrator import gate_a
    sys.argv = ["glitchhunter demo", a.scenario, "--samples", str(a.samples), "--k", str(a.k)] + ([] if a.no_decoys else ["--decoys"])
    return 0 if gate_a.main() else 1

# ------------------------------------------------------------------ parser
def build():
    p = argparse.ArgumentParser(prog="glitchhunter", description="Find, reproduce and fix race conditions in database-backed APIs. Start with: doctor, then demo wallet.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Typical flow:\n  .\\glitchhunter doctor\n  .\\glitchhunter checks wallet --propose --filter --auto-approve\n  .\\glitchhunter scan wallet\n  .\\glitchhunter repair wallet\n  .\\glitchhunter test wallet\n\nExit codes: 0 fine, 1 bug found / fix not accepted, 2 setup problem.")
    p.add_argument("--debug", action="store_true", help="show Python tracebacks")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")
    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_, description=help_); s.set_defaults(func=fn); return s
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
    s = add("upload", cmd_upload, "add your own FastAPI + PostgreSQL app as a scenario")
    s.add_argument("--name", required=True); s.add_argument("--app", required=True, help=".py file or .zip"); s.add_argument("--sql", required=True, help="setup SQL that creates the tables")
    s.add_argument("--env", default="DATABASE_URL", help="env var your app reads for the database URL"); s.add_argument("--endpoint", help='for example "POST /book"; default: the best candidate')
    s.add_argument("--params", help='request values as JSON, for example \'{"qty": 1}\''); s.add_argument("-n", type=int, default=6, help="simultaneous requests"); s.add_argument("--state", help="table.column to watch, for example seats.seats_left")
    s = add("delete-project", cmd_delete, "remove an uploaded app, its files and its database schema"); s.add_argument("project", help="project id (the part after custom_)")
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
