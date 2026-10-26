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

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
    r.onerror = () => reject(new Error("Could not read that file."));
    r.readAsDataURL(file);
  });
}

export default function TryYourOwn() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sql, setSql] = useState("");
  const [dbEnv, setDbEnv] = useState("DATABASE_URL");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [chosen, setChosen] = useState<ProjectEndpoint | null>(null);
  const [params, setParams] = useState("{}");
  const [raceN, setRaceN] = useState(6);
  const [stateTable, setStateTable] = useState("");
  const [stateColumn, setStateColumn] = useState("");

  async function scan() {
    setBusy("scan"); setError(null);
    try {
      if (!file) throw new Error("Choose your app file (.py or .zip).");
      const p = await uploadProject({ name: name.trim(), filename: file.name, content_b64: await toBase64(file), setup_sql: sql, db_env: dbEnv.trim() || "DATABASE_URL" });
      setProject(p);
      const first = p.endpoints.find((e) => e.supported) ?? null;
      setChosen(first); setParams(JSON.stringify(first?.sample_params ?? {}));
      setStateTable(p.suggested_state?.table ?? p.tables[0] ?? ""); setStateColumn(p.suggested_state?.column ?? "");
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  async function create() {
    if (!project || !chosen) return;
    setBusy("create"); setError(null);
    try {
      let parsed: Record<string, unknown>;
      try { parsed = JSON.parse(params || "{}"); } catch { throw new Error("The request values must be valid JSON, for example {\"qty\": 1}."); }
      const s = await createScenario(project.id, { method: chosen.method, path: chosen.path, params: parsed, race_n: raceN, state: stateTable && stateColumn ? { table: stateTable, column: stateColumn } : null });
      router.push(`/scenarios/${s.id}`);
    } catch (e) { setError((e as Error).message); setBusy(null); }
  }

  return (
    <>
      <p><Link href="/">← All examples</Link></p>
      <h1>Try your own app</h1>
      <p className="lead">Upload a small FastAPI app that uses PostgreSQL. GlitchHunter will attack one of its endpoints with simultaneous requests, show what goes wrong, and test a fix.</p>

      <div className="notice-box">
        <b>Before you upload</b>
        <ul>
          <li>Your code is <b>run on this computer</b>. Only upload code you trust.</li>
          <li>It must be a <b>FastAPI</b> app (<code>app = FastAPI()</code>) that talks to <b>PostgreSQL through psycopg2</b>, with endpoints written as <code>@app.post("/path")</code> and values passed as query parameters.</li>
          <li>It must read its database address from an <b>environment variable</b> (default <code>DATABASE_URL</code>). We give it a private copy of the database, so your real data is never touched.</li>
          <li>To make timing problems easier to catch, we slow down the app&apos;s database reads slightly <b>in our test copy</b>. We never change your files.</li>
        </ul>
      </div>

      <section className="sec">
        <div className="secnum">1</div>
        <div className="secbody">
          <h2>Upload your app</h2>
          <label className="field"><span>Name</span><input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ticket shop" /></label>
          <label className="field"><span>App file (.py, or a .zip of the folder)</span><input type="file" accept=".py,.zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
          <label className="field"><span>Setup SQL: creates your tables with a few starting rows (we rerun it before every try)</span>
            <textarea rows={6} value={sql} onChange={(e) => setSql(e.target.value)} placeholder={EXAMPLE_SQL} spellCheck={false} />
          </label>
          <p className="small"><a href="#" onClick={(e) => { e.preventDefault(); setSql(EXAMPLE_SQL); }}>Use the example setup SQL</a> (for the sample ticket-shop app)</p>
          <label className="field"><span>Environment variable your app reads for the database address</span><input type="text" value={dbEnv} onChange={(e) => setDbEnv(e.target.value)} /></label>
          <button disabled={busy !== null || !name.trim() || !file || !sql.trim()} onClick={scan}>{busy === "scan" ? "Scanning…" : "Upload and scan"}</button>{" "}
          {busy === "scan" && <Busy text="Reading your code and checking the setup SQL…" />}
          <ErrorBox message={error} />
        </div>
      </section>

      {project && (
        <section className="sec">
          <div className="secnum">2</div>
          <div className="secbody">
            <h2>Pick the endpoint to attack</h2>
            <p className="muted">Found your app in <code>{project.entry.file}</code> with {project.endpoints.length} endpoint{project.endpoints.length === 1 ? "" : "s"} and the table{project.tables.length > 1 ? "s" : ""} {project.tables.join(", ")}. Endpoints that read and then write are the ones where this kind of bug usually hides.</p>
            {project.warnings.map((w) => <div key={w} className="notice">{w}</div>)}
            {project.endpoints.map((e) => (
              <label key={`${e.method} ${e.path}`} className={`choice ${chosen === e ? "on" : ""} ${e.supported ? "" : "off"}`}>
                <input type="radio" name="ep" disabled={!e.supported} checked={chosen === e} onChange={() => { setChosen(e); setParams(JSON.stringify(e.sample_params)); }} />
                <span><b>{e.method} {e.path}</b> <span className="muted small">· {e.hint}{e.supported ? "" : ` · not supported: ${e.unsupported_reason}`}</span></span>
              </label>
            ))}
            <label className="field"><span>Values to send with each request (JSON)</span><input type="text" value={params} onChange={(e) => setParams(e.target.value)} spellCheck={false} /></label>
            <div className="row">
              <label className="field narrow"><span>Simultaneous requests</span><input type="number" min={2} max={20} value={raceN} onChange={(e) => setRaceN(Number(e.target.value))} /></label>
              <label className="field narrow"><span>Number to watch: table</span><input type="text" value={stateTable} onChange={(e) => setStateTable(e.target.value)} /></label>
              <label className="field narrow"><span>column</span><input type="text" value={stateColumn} onChange={(e) => setStateColumn(e.target.value)} /></label>
            </div>
            <p className="small muted">“Number to watch” is shown before and after each try (for a shop, the seats left or the stock).</p>
            <button disabled={busy !== null || !chosen} onClick={create}>{busy === "create" ? "Creating…" : "Create and open"}</button>
          </div>
        </section>
      )}
    </>
  );
}
