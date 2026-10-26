"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { createScenario, uploadProject } from "@/lib/api";
import type { Project, ProjectEndpoint } from "@/lib/types";
import { Busy, ErrorBox } from "@/components/ui";

const EXAMPLE_SQL = `DROP TABLE IF EXISTS seats;
CREATE TABLE seats (event_id int PRIMARY KEY, seats_left int NOT NULL);
INSERT INTO seats VALUES (1, 3);`;
const NUMERIC = ["integer", "bigint", "smallint", "numeric", "real", "double precision", "decimal"];

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
    r.onerror = () => reject(new Error("Could not read that file."));
    r.readAsDataURL(file);
  });
}

function parseJson(text: string, what: string): unknown {
  if (!text.trim()) return null;
  try { return JSON.parse(text); } catch { throw new Error(`${what} must be valid JSON.`); }
}

function parseEnv(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i < 1) throw new Error(`Extra environment variables must look like NAME=value (one per line). Problem line: "${line}"`);
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

export default function TryYourOwn() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sql, setSql] = useState("");
  const [dbEnv, setDbEnv] = useState("DATABASE_URL");
  const [dbScheme, setDbScheme] = useState("postgresql");
  const [envText, setEnvText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [chosen, setChosen] = useState<ProjectEndpoint | null>(null);
  const [query, setQuery] = useState("{}");
  const [pathVals, setPathVals] = useState("{}");
  const [body, setBody] = useState("");
  const [authValue, setAuthValue] = useState("");
  const [extraHeaders, setExtraHeaders] = useState<Record<string, string>>({});
  const [raceN, setRaceN] = useState(6);
  const [pause, setPause] = useState(25);
  const [qtyKey, setQtyKey] = useState("");
  const [stateTable, setStateTable] = useState("");
  const [stateColumn, setStateColumn] = useState("");

  function pick(e: ProjectEndpoint) {
    setChosen(e);
    setQuery(JSON.stringify(e.sample_params)); setPathVals(JSON.stringify(e.sample_path_params));
    setBody(e.sample_json === null || e.sample_json === undefined ? "" : JSON.stringify(e.sample_json, null, 2));
    setAuthValue(e.auth ? e.auth.prefix : ""); setExtraHeaders({ ...e.required_headers }); setQtyKey(e.suggested_qty ?? "");
  }

  async function scan() {
    setBusy("scan"); setError(null);
    try {
      if (!file) throw new Error("Choose your app file (.py or .zip).");
      const p = await uploadProject({ name: name.trim(), filename: file.name, content_b64: await toBase64(file), setup_sql: sql, db_env: dbEnv.trim() || "DATABASE_URL", db_scheme: dbScheme, env: parseEnv(envText) });
      setProject(p);
      const first = p.endpoints.find((e) => e.supported) ?? null;
      if (first) pick(first);
      setStateTable(p.suggested_state?.table ?? p.tables[0] ?? ""); setStateColumn(p.suggested_state?.column ?? "");
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  async function create() {
    if (!project || !chosen) return;
    setBusy("create"); setError(null);
    try {
      const headers: Record<string, string> = { ...extraHeaders };
      if (chosen.auth) headers[chosen.auth.header] = authValue.trim();
      const q = parseJson(query, "The query values") ?? {}, p = parseJson(pathVals, "The path values") ?? {};
      const s = await createScenario(project.id, {
        method: chosen.method, path: chosen.path, params: q as Record<string, unknown>, path_params: p as Record<string, unknown>,
        json: body.trim() ? parseJson(body, "The JSON body") : null, headers, race_n: raceN, pause_ms: pause,
        state: stateTable && stateColumn ? { table: stateTable, column: stateColumn } : null, qty_key: qtyKey || null,
      });
      router.push(`/scenarios/${s.id}`);
    } catch (e) { setError((e as Error).message); setBusy(null); }
  }

  const numericCols = (t: string) => (project?.columns[t] ?? []).filter((c) => NUMERIC.includes(c.type)).map((c) => c.name);
  const hasPath = !!chosen && /\{\w+\}/.test(chosen.path);

  return (
    <>
      <p><Link href="/">← All examples</Link></p>
      <h1>Try your own app</h1>
      <p className="lead">Upload a FastAPI app that uses PostgreSQL. GlitchHunter starts it, finds its endpoints, attacks one with simultaneous requests, shows what goes wrong, and tests a fix.</p>

      <div className="notice-box">
        <b>Before you upload</b>
        <ul>
          <li>Your code is <b>run on this computer</b>. Only upload code you trust.</li>
          <li>It must be a <b>FastAPI</b> app that talks to <b>PostgreSQL</b> through psycopg2 or a <b>synchronous SQLAlchemy</b> engine. Routers with prefixes, JSON bodies and one login header are supported. File uploads, form bodies, cookie logins and async database drivers are not.</li>
          <li>Upload the whole folder as a <b>.zip</b> if it has several files (without <code>venv</code> or <code>.git</code>). Its Python packages must already be installed here.</li>
          <li>It must read its database address from an <b>environment variable</b> (default <code>DATABASE_URL</code>). We give it a private copy of the database, so your real data is never touched.</li>
          <li>To make timing problems easier to catch, we slow down the app&apos;s database reads slightly <b>in our test copy</b>. We never change your files.</li>
        </ul>
      </div>

      <section className="sec">
        <div className="secnum">1</div>
        <div className="secbody">
          <h2>Upload your app</h2>
          <label className="field"><span>Name</span><input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Shop service" /></label>
          <label className="field"><span>App file (.py, or a .zip of the folder)</span><input type="file" accept=".py,.zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
          <label className="field"><span>Setup SQL: resets your tables and inserts a few starting rows (we rerun it before every try). If your app creates its own tables on start-up, use TRUNCATE ... then INSERT.</span>
            <textarea rows={6} value={sql} onChange={(e) => setSql(e.target.value)} placeholder={EXAMPLE_SQL} spellCheck={false} />
          </label>
          <p className="small"><a href="#" onClick={(e) => { e.preventDefault(); setSql(EXAMPLE_SQL); }}>Use the example setup SQL</a> (for the sample ticket-shop app)</p>
          <details>
            <summary>Advanced: environment variables and database URL style</summary>
            <label className="field"><span>Environment variable your app reads for the database address</span><input type="text" value={dbEnv} onChange={(e) => setDbEnv(e.target.value)} /></label>
            <label className="field"><span>Database URL style (SQLAlchemy apps often need postgresql+psycopg2)</span>
              <select value={dbScheme} onChange={(e) => setDbScheme(e.target.value)}>
                <option value="postgresql">postgresql://</option><option value="postgresql+psycopg2">postgresql+psycopg2://</option><option value="postgresql+psycopg">postgresql+psycopg://</option>
              </select>
            </label>
            <label className="field"><span>Extra environment variables your app needs (NAME=value, one per line). Stored only on this computer; use test values, not real secrets.</span>
              <textarea rows={3} value={envText} onChange={(e) => setEnvText(e.target.value)} placeholder={"API_TOKEN=test-token\nSECRET_KEY=test-secret"} spellCheck={false} />
            </label>
          </details>
          <p><button disabled={busy !== null || !name.trim() || !file || !sql.trim()} onClick={scan}>{busy === "scan" ? "Starting your app…" : "Upload and scan"}</button>{" "}
            {busy === "scan" && <Busy text="Starting your app once to see what it serves, then checking the setup SQL…" />}</p>
          <ErrorBox message={project ? null : error} />
        </div>
      </section>

      {project && (
        <section className="sec">
          <div className="secnum">2</div>
          <div className="secbody">
            <h2>Pick the endpoint to attack</h2>
            <p className="muted">Started <code>{project.entry.module}:{project.entry.var}</code> and found {project.endpoints.length} endpoint{project.endpoints.length === 1 ? "" : "s"} and the table{project.tables.length > 1 ? "s" : ""} {project.tables.join(", ")}. Endpoints that read and then write are where this kind of bug usually hides.</p>
            {project.warnings.map((w) => <div key={w} className="notice">{w}</div>)}
            {project.endpoints.map((e) => (
              <label key={`${e.method} ${e.path}`} className={`choice ${chosen === e ? "on" : ""} ${e.supported ? "" : "off"}`}>
                <input type="radio" name="ep" disabled={!e.supported} checked={chosen === e} onChange={() => pick(e)} />
                <span>
                  <b>{e.method} {e.path}</b> <span className="muted small">· {e.hint}</span>
                  <span className="small muted" style={{ display: "block" }}>
                    {e.auth && <span className="badge grey" style={{ marginRight: 6 }}>needs {e.auth.header} header</span>}
                    {e.sample_json !== null && e.sample_json !== undefined && <span className="badge grey" style={{ marginRight: 6 }}>JSON body</span>}
                    <span className="muted">{e.file}:{e.lineno}</span>
                  </span>
                  {e.unsupported_reasons.map((r) => <span key={r} className="small" style={{ display: "block", color: "var(--bad)" }}>Not supported: {r}</span>)}
                </span>
              </label>
            ))}

            {chosen && (
              <>
                <h3 style={{ marginTop: 18 }}>What each request sends</h3>
                {chosen.auth && (
                  <label className="field"><span>{chosen.auth.header} header (a test token that your app accepts, for example “{chosen.auth.prefix}test-token”)</span>
                    <input type="text" value={authValue} onChange={(e) => setAuthValue(e.target.value)} spellCheck={false} /></label>
                )}
                {Object.keys(extraHeaders).map((h) => (
                  <label className="field" key={h}><span>{h} header (required by this endpoint)</span><input type="text" value={extraHeaders[h]} onChange={(e) => setExtraHeaders({ ...extraHeaders, [h]: e.target.value })} /></label>
                ))}
                {hasPath && <label className="field"><span>Path values, for the {"{placeholders}"} in the address (JSON)</span><input type="text" value={pathVals} onChange={(e) => setPathVals(e.target.value)} spellCheck={false} /></label>}
                <label className="field"><span>Query values (JSON, usually empty)</span><input type="text" value={query} onChange={(e) => setQuery(e.target.value)} spellCheck={false} /></label>
                {(chosen.sample_json !== null && chosen.sample_json !== undefined) || body ? (
                  <label className="field"><span>JSON body (a sample built from your app&apos;s schema: use values that exist in your setup SQL)</span>
                    <textarea rows={5} value={body} onChange={(e) => setBody(e.target.value)} spellCheck={false} /></label>
                ) : null}
                <div className="row">
                  <label className="field narrow"><span>Simultaneous requests</span><input type="number" min={2} max={20} value={raceN} onChange={(e) => setRaceN(Number(e.target.value))} /></label>
                  <label className="field narrow"><span>How much each request takes</span>
                    <select value={qtyKey} onChange={(e) => setQtyKey(e.target.value)}>
                      <option value="">(not applicable)</option>
                      {chosen.qty_candidates.map((k) => <option key={k} value={k}>{k}</option>)}
                    </select>
                  </label>
                </div>
                <div className="row">
                  <label className="field narrow"><span>Number to watch: table</span>
                    <select value={stateTable} onChange={(e) => { setStateTable(e.target.value); setStateColumn(numericCols(e.target.value)[0] ?? ""); }}>
                      {project.tables.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </label>
                  <label className="field narrow"><span>column</span>
                    <select value={stateColumn} onChange={(e) => setStateColumn(e.target.value)}>
                      {numericCols(stateTable).map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </label>
                </div>
                <p className="small muted">“Number to watch” is shown before and after each try (for a shop, the stock or seats left). “How much each request takes” lets us say “6 were taken but only 3 existed”.</p>
                <details>
                  <summary>Advanced</summary>
                  <label className="field narrow"><span>Pause after each database read in our test copy (ms)</span><input type="number" min={0} max={500} value={pause} onChange={(e) => setPause(Number(e.target.value))} /></label>
                </details>
              </>
            )}
            <ErrorBox message={project ? error : null} />
            <p><button disabled={busy !== null || !chosen} onClick={create}>{busy === "create" ? "Creating…" : "Create and open"}</button></p>
          </div>
        </section>
      )}
    </>
  );
}
