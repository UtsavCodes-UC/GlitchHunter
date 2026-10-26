"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { deleteUpload, getJob, getSource, getUpload, saveSetup, startCheck } from "@/lib/api";
import type { Job, ScanRoute, Setup, UploadDetail } from "@/lib/types";
import { Busy, ErrorBox } from "@/components/ui";

const VERDICT_TEXT: Record<string, string> = {
  suspect: "looks risky", guarded: "guarded", writes: "writes", "read-only": "read-only",
};
const VERDICT_CLASS: Record<string, string> = { suspect: "bad", guarded: "ok", writes: "warn", "read-only": "grey" };

function envToText(e: Record<string, string>) { return Object.entries(e).map(([k, v]) => `${k}=${v}`).join("\n"); }
function parseEnv(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i < 1) throw new Error(`Environment variables must look like NAME=value, one per line. Problem line: "${line}"`);
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

function RouteRow({ id, r, onUse }: { id: string; r: ScanRoute; onUse: (r: ScanRoute) => void }) {
  const [code, setCode] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function show() {
    if (code !== null) { setCode(null); return; }
    try { setCode((await getSource(id, r.file, r.function)).code); } catch (e) { setErr((e as Error).message); }
  }
  return (
    <tr>
      <td data-label="Endpoint"><b>{r.method}</b> <code>{r.path}</code><div className="small muted">{r.file}:{r.lineno} · {r.function}</div></td>
      <td data-label="Hint"><span className={`badge ${VERDICT_CLASS[r.verdict]}`}>{VERDICT_TEXT[r.verdict]}</span></td>
      <td className="small" data-label="Why">
        {r.reasons.join(" ")}
        {code !== null && <pre>{code}</pre>}
        <ErrorBox message={err} />
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <button className="secondary" onClick={show} style={{ padding: "4px 10px" }}>{code !== null ? "Hide code" : "Show code"}</button>{" "}
        <button disabled={!r.app} title={r.app ? "" : "no app serves this route"} onClick={() => onUse(r)} style={{ padding: "4px 10px" }}>Use this</button>
      </td>
    </tr>
  );
}

function Project() {
  const id = useSearchParams().get("id") ?? "";
  const router = useRouter();
  const [p, setP] = useState<UploadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<Setup | null>(null);
  const [burstText, setBurstText] = useState("");
  const [envText, setEnvText] = useState("");
  const [hdrText, setHdrText] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);

  function fill(s: Setup) {
    setForm(s); setBurstText(`[\n${s.burst.map((x) => " " + JSON.stringify(x)).join(",\n")}\n]`);
    setEnvText(envToText(s.env ?? {})); setHdrText(Object.entries(s.headers ?? {}).map(([k, v]) => `${k}: ${v}`).join("\n"));
  }
  useEffect(() => {
    if (!id) return;
    getUpload(id).then((d) => { setP(d); const s = d.config ?? d.suggested; if (s) fill(s); }).catch((e) => setError((e as Error).message));
  }, [id]);
  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight }); }, [job?.log.length]);

  function use(r: ScanRoute) {
    if (!p || !r.app) return;
    const f = form ?? p.suggested;
    fill({ app: r.app, file: r.file, func: r.function, method: r.method, path: r.path, body: r.body ? "json" : "query", burst: Array.from({ length: 4 }, () => ({ ...r.sample })),
      schema_sql: f?.schema_sql ?? p.scan.schema_sql, seed_sql: f?.seed_sql ?? p.scan.seed_sql, db_env: f?.db_env ?? p.scan.db_env.guess, env: f?.env ?? p.scan.db_env.env, headers: f?.headers });
    document.getElementById("setup")?.scrollIntoView({ behavior: "smooth" });
  }

  function collect(): Setup {
    if (!form) throw new Error("Pick an endpoint first.");
    let burst: unknown;
    try { burst = JSON.parse(burstText); } catch { throw new Error("The requests must be valid JSON: a list like [{\"qty\": 1}, {\"qty\": 1}]."); }
    if (!Array.isArray(burst)) throw new Error("The requests must be a JSON list.");
    const headers: Record<string, string> = {};
    for (const line of hdrText.split("\n").map((l) => l.trim()).filter(Boolean)) {
      const i = line.indexOf(":"); if (i < 1) throw new Error(`Headers must look like Name: value. Problem line: "${line}"`);
      headers[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
    return { ...form, burst: burst as Record<string, unknown>[], env: parseEnv(envText), headers };
  }

  async function saveAndTest() {
    setError(null); setJob(null); setBusy(true);
    try {
      const saved = await saveSetup(id, collect()); setP(saved);
      const jid = await startCheck(id);
      for (;;) {
        const j = await getJob(id, jid); setJob(j);
        if (j.status !== "running") break;
        await new Promise((r) => setTimeout(r, 700));
      }
      setP(await getUpload(id));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function remove() {
    if (!confirm("Delete this project? Its files, its database account and its results are removed.")) return;
    try { await deleteUpload(id); router.push("/"); } catch (e) { setError((e as Error).message); }
  }

  if (!id) return <p>No project selected. <Link href="/">Back</Link></p>;
  if (!p) return <><p><Link href="/">← Back</Link></p><ErrorBox message={error} />{!error && <p className="muted">Loading…</p>}</>;
  const set = (k: keyof Setup, v: unknown) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const res = job?.result;

  return (
    <div className="narrow">
      <p><Link href="/">← Back</Link></p>
      <div className="row spread"><h1 style={{ margin: 0 }}>{p.name}</h1><span className={`badge ${p.status === "set up" ? "ok" : "grey"}`}>{p.status}</span></div>
      <p className="muted"><code>{p.id}</code> · {p.files.length} files kept{p.skipped ? `, ${p.skipped} skipped (not source files)` : ""} · {p.scan.routes.length} endpoint(s) · nothing has been run yet</p>
      {p.scan.warnings.map((w) => <div key={w} className="notice">{w}</div>)}
      <ErrorBox message={error} />

      <section className="sec">
        <div className="secnum">A</div>
        <div className="secbody">
          <h2>What we found in your code</h2>
          <p className="muted">Read from the source text only. The labels are <b>hints from code patterns</b>, not verdicts: “looks risky” means it reads a value, then writes it back, with no lock or atomic UPDATE in sight.</p>
          {p.scan.routes.length === 0 ? <p>No endpoints were found. Check that this is a FastAPI app.</p> : (
            <div className="tbl-wrap"><table className="tbl scan">
              <thead><tr><th>Endpoint</th><th>Hint</th><th>Why</th><th /></tr></thead>
              <tbody>{p.scan.routes.map((r) => <RouteRow key={`${r.method} ${r.path} ${r.file}:${r.lineno}`} id={p.id} r={r} onUse={use} />)}</tbody>
            </table></div>
          )}
        </div>
      </section>

      <section className="sec" id="setup">
        <div className="secnum">B</div>
        <div className="secbody">
          <h2>Set it up</h2>
          <p className="muted">Pre-filled from the scan: check it, change what is wrong, then test it once.</p>
          {form && (
            <>
              <div className="row">
                <label className="field narrow"><span>How to start the app (module:variable)</span><input type="text" value={form.app} onChange={(e) => set("app", e.target.value)} spellCheck={false} /></label>
                <label className="field narrow"><span>Environment variable for the database address</span><input type="text" value={form.db_env} onChange={(e) => set("db_env", e.target.value)} spellCheck={false} /></label>
              </div>
              <div className="row">
                <label className="field narrow"><span>File with the endpoint function</span>
                  <select value={form.file} onChange={(e) => set("file", e.target.value)}>{p.files.filter((f) => f.endsWith(".py")).map((f) => <option key={f}>{f}</option>)}</select></label>
                <label className="field narrow"><span>Function name</span><input type="text" value={form.func} onChange={(e) => set("func", e.target.value)} spellCheck={false} /></label>
                <label className="field narrow" style={{ flex: "0 1 110px" }}><span>Method</span>
                  <select value={form.method} onChange={(e) => set("method", e.target.value)}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}</select></label>
              </div>
              <div className="row">
                <label className="field narrow" style={{ flex: "2 1 260px" }}><span>Path (use {"{placeholders}"} for path values)</span><input type="text" value={form.path} onChange={(e) => set("path", e.target.value)} spellCheck={false} /></label>
                <label className="field narrow"><span>Other values are sent as</span>
                  <select value={form.body} onChange={(e) => set("body", e.target.value as "json" | "query")}><option value="json">a JSON body</option><option value="query">query parameters</option></select></label>
              </div>
              <label className="field"><span>The requests sent together in one try (2 to 50, a JSON list, one object per request; include values for {"{placeholders}"})</span>
                <textarea rows={6} value={burstText} onChange={(e) => setBurstText(e.target.value)} spellCheck={false} /></label>
              <label className="field"><span>Schema SQL: creates your tables (rerun before the app starts; leave empty if the app creates its own tables)
                {p.scan.schema_source && form.schema_sql === p.scan.schema_sql ? ` · guessed from ${p.scan.schema_source}` : ""}</span>
                <textarea rows={6} value={form.schema_sql} onChange={(e) => set("schema_sql", e.target.value)} spellCheck={false} /></label>
              <label className="field"><span>Seed SQL: the starting rows (rerun before every try). Tip: make the stock small, like 1, so two buyers cannot both succeed.</span>
                <textarea rows={4} value={form.seed_sql} onChange={(e) => set("seed_sql", e.target.value)} spellCheck={false} /></label>
              <details>
                <summary>Advanced: environment variables, a login header, database URL style</summary>
                <label className="field"><span>Environment variables your app needs (NAME=value per line). Use ${"{PGHOST}"}, ${"{PGPORT}"}, ${"{PGUSER}"}, ${"{PGPASSWORD}"}, ${"{PGDATABASE}"} or ${"{DB_URL}"} to point at the private database without typing a password.</span>
                  <textarea rows={3} value={envText} onChange={(e) => setEnvText(e.target.value)} spellCheck={false} placeholder={"DB_HOST=${PGHOST}\nAPI_TOKEN=test-token"} /></label>
                <label className="field"><span>Request headers (Name: value per line), for example a test login token</span>
                  <textarea rows={2} value={hdrText} onChange={(e) => setHdrText(e.target.value)} spellCheck={false} placeholder="Authorization: Bearer test-token" /></label>
                <label className="field narrow"><span>Database URL style (SQLAlchemy apps often need postgresql+psycopg2)</span>
                  <select value={form.db_scheme ?? "postgresql"} onChange={(e) => set("db_scheme", e.target.value)}>
                    <option value="postgresql">postgresql://</option><option value="postgresql+psycopg2">postgresql+psycopg2://</option><option value="postgresql+psycopg">postgresql+psycopg://</option>
                  </select></label>
                <label className="field narrow"><span>Pause after each database read in our test copy (ms)</span>
                  <input type="number" min={0} max={500} value={form.pause_ms ?? 25} onChange={(e) => set("pause_ms", Number(e.target.value))} /></label>
              </details>
              <p>
                <button disabled={busy} onClick={saveAndTest}>{busy ? "Testing…" : "Save and test the setup"}</button>{" "}
                {busy && <Busy text="Running your app once, in isolation…" />}
              </p>
            </>
          )}
        </div>
      </section>

      {(job || p.status === "set up") && (
        <section className="sec">
          <div className="secnum">C</div>
          <div className="secbody">
            <h2>Test result</h2>
            {job && <pre ref={logRef} className="log">{job.log.map((l) => `[${l.t.toFixed(1).padStart(5)}s] ${l.msg}`).join("\n") || "starting…"}</pre>}
            {res && (
              <div className={`verdict ${res.verdict === "ok" ? "ok" : res.verdict === "warning" ? "warn" : "bad"}`}>
                {res.verdict === "ok" ? "✔ Works: " : res.verdict === "warning" ? "⚠ Works, with a warning: " : "✖ Problem: "}{res.message}
              </div>
            )}
            {res?.final_tables && (
              <details style={{ marginTop: 8 }}><summary className="small">Tables after the test burst</summary><pre>{JSON.stringify(res.final_tables, null, 1)}</pre></details>
            )}
          </div>
        </section>
      )}

      <section className="sec">
        <div className="secnum">D</div>
        <div className="secbody">
          <h2>Find the bug and fix it</h2>
          {p.status === "set up" ? (
            <><p className="muted">The setup works. The next pages are the same ones the built-in examples use.</p>
              <Link href={`/scenarios/${p.id}`} className="btn">Open the attack and fix steps →</Link></>
          ) : <p className="muted">Available after the setup has been saved and tested.</p>}
          <p style={{ marginTop: 24 }}><button className="danger" onClick={remove}>Delete this project</button></p>
        </div>
      </section>
    </div>
  );
}

export default function ProjectPage() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><Project /></Suspense>;
}
