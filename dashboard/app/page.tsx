"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { listScenarios } from "@/lib/api";
import { useScenario } from "@/lib/useScenario";
import type { Scenario } from "@/lib/types";
import { ErrorBox } from "@/components/ui";

function ScenarioCard({ s }: { s: Scenario }) {
  const { stages } = useScenario(s.id);
  return (
    <div className="card">
      <div className="row spread">
        <h3 style={{ textTransform: "capitalize" }}>{s.id}</h3>
        <Link href={`/scenarios/${s.id}`} className="btn" style={{ textDecoration: "none" }}>Open</Link>
      </div>
      <div className="muted small">Attacks <code>{s.endpoint.method} {s.endpoint.path}</code> with {JSON.stringify(s.endpoint.params)}</div>
      <div className="row" style={{ marginTop: 12, gap: 6 }}>
        {stages.map((st, i) => (
          <span key={st.key} className={`badge ${st.done ? "ok" : "grey"}`} title={st.detail}>{i + 1}. {st.label}</span>
        ))}
      </div>
    </div>
  );
}

export default function Home() {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { listScenarios().then(setScenarios).catch((e) => setError((e as Error).message)); }, []);
  return (
    <>
      <h1>Scenarios</h1>
      <p className="muted">Each scenario is a demo app with a deliberate race. The loop is: propose rules, filter them, attack, explain the failing run, repair.</p>
      <ErrorBox message={error} />
      {!scenarios && !error && <p className="muted">Loading…</p>}
      <div className="cards">{scenarios?.map((s) => <ScenarioCard key={s.id} s={s} />)}</div>
    </>
  );
}
