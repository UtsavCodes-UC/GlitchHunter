"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getHealth, listScenarios, listUploads } from "@/lib/api";
import { copyFor } from "@/lib/copy";
import type { Scenario, UploadSummary } from "@/lib/types";
import { ErrorBox } from "@/components/ui";
import UploadBox from "@/components/UploadBox";

export default function Home() {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [projects, setProjects] = useState<UploadSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadsOn, setUploadsOn] = useState(true);   // a public deployment can switch uploads off
  useEffect(() => {
    getHealth().then((h) => setUploadsOn(h.uploads !== false)).catch(() => { /* keep the default */ });
    listScenarios().then(setScenarios).catch((e) => setError((e as Error).message));
    listUploads().then(setProjects).catch(() => setProjects([]));   // only used for the "continue" links: a failure just hides them
  }, []);
  const demos = scenarios?.filter((s) => !s.custom) ?? [];

  return (
    <>
      <section className="top">
        <div>
          <h1>₹100 in the wallet. ₹160 paid out.</h1>
          <p>
            Most read-check-write bugs never show up in tests that send one request at a time. GlitchHunter sends them together to the real database,
            keeps the run that broke your rules, and only accepts a fix once that exact run comes back clean.
          </p>
          <div className="cta">
            <Link href="/#demos" className="btn lg">Try a demo</Link>
            {uploadsOn && <Link href="/#upload" className="btn ghost lg">Use your own code</Link>}
          </div>
        </div>
        <p className="note">
          It reproduces bugs and checks fixes. It does not prove a race is gone: zero violations in a hundred tries is evidence, not proof. Point it at test data, never production.
        </p>
      </section>

      <section className="steps" aria-label="How it works">
        <div><span className="n">01</span><h3>Break it</h3><p>Send the same requests at the same instant, again and again.</p></div>
        <div><span className="n">02</span><h3>Know it is wrong</h3><p>Checks that must always hold tell us when the result makes no sense.</p></div>
        <div><span className="n">03</span><h3>Fix it and prove it</h3><p>An AI proposes a fix; we test it on a copy before you trust it.</p></div>
      </section>

      <section className="block" id="demos">
        <span className="label">Try a demo</span>
        <ErrorBox message={error} />
        {scenarios === null && !error && <div aria-busy="true"><div className="sk" /><div className="sk" /></div>}
        {scenarios !== null && (
          <table className="rows">
            <thead><tr><th>Scenario</th><th>Endpoint</th><th className="go"><span className="sr">Open</span></th></tr></thead>
            <tbody>
              {demos.map((s) => {
                const c = copyFor(s.id, s);
                return (
                  <tr key={s.id}>
                    <td><div className="t"><Link href={`/scenarios/${s.id}`}>{c.title}</Link></div><div className="d">{c.story}</div></td>
                    <td className="ep" data-label="Endpoint">{s.endpoint.method} {s.endpoint.path}</td>
                    <td className="go"><Link href={`/scenarios/${s.id}`} className="btn">Run this demo</Link></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {uploadsOn && (
      <section className="block" id="upload">
        <span className="label">Use your own code</span>
        <UploadBox />
        {projects.length > 0 && (
          <p className="recent">
            <span>Continue with:</span>
            {projects.slice(0, 4).map((p) => (
              <span key={p.id}><Link href={p.status === "set up" ? `/scenarios/${p.id}` : `/project?id=${p.id}`}>{p.name}</Link><span className={`badge ${p.status === "set up" ? "ok" : "warn"}`}>{p.status}</span></span>
            ))}
          </p>
        )}
      </section>
      )}

      <footer className="foot">GlitchHunter reproduces and validates concurrency bugs. A passing fix is evidence, not proof.</footer>
    </>
  );
}
