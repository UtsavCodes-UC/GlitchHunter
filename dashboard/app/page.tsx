"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { listScenarios } from "@/lib/api";
import { copyFor } from "@/lib/copy";
import type { Scenario } from "@/lib/types";
import { ErrorBox } from "@/components/ui";

export default function Home() {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { listScenarios().then(setScenarios).catch((e) => setError((e as Error).message)); }, []);
  return (
    <>
      <h1>Does your app break when two people click at the same time?</h1>
      <p className="lead">
        Some bugs only appear when two requests arrive at the exact same moment: two withdrawals from one wallet, two shoppers buying the last item.
        Normal tests never see them. GlitchHunter makes it happen on purpose, shows you what goes wrong, and checks that a fix really works.
      </p>
      <div className="three">
        <div><b>1. See the bug</b><br /><span className="muted">We send requests at the same instant, many times.</span></div>
        <div><b>2. Know it is wrong</b><br /><span className="muted">Checks tell us when the result makes no sense.</span></div>
        <div><b>3. Fix it and prove it</b><br /><span className="muted">An AI proposes a fix. We test it before you trust it.</span></div>
      </div>
      <h2>Pick an example to try</h2>
      <ErrorBox message={error} />
      {!scenarios && !error && <p className="muted">Loading…</p>}
      <div className="cards">
        {scenarios?.map((s) => {
          const c = copyFor(s.id);
          return (
            <Link key={s.id} href={`/scenarios/${s.id}`} className="card pick">
              <h3>{c.title}</h3>
              <p className="muted" style={{ margin: "4px 0 12px" }}>{c.story}</p>
              <span className="btn">Start →</span>
            </Link>
          );
        })}
      </div>
    </>
  );
}
