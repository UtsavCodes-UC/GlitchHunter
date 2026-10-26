"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getHealth, listScenarios } from "@/lib/api";
import { copyFor } from "@/lib/copy";
import type { Scenario } from "@/lib/types";

export default function Nav() {
  const path = usePathname();
  const [demos, setDemos] = useState<Scenario[]>([]);
  const [model, setModel] = useState<string | null | undefined>(undefined);   // undefined = loading, null = backend not reachable
  useEffect(() => {
    listScenarios().then((l) => setDemos(l.filter((s) => !s.custom))).catch(() => setDemos([]));
    getHealth().then((h) => setModel(h.model ?? "API connected")).catch(() => setModel(null));
  }, []);
  return (
    <header className="nav">
      <div className="nav-in">
        <Link href="/" className="brand"><b>Glitch</b>Hunter</Link>
        <nav className="nav-links" aria-label="Main">
          {demos.map((s) => (
            <Link key={s.id} href={`/scenarios/${s.id}`} aria-current={path === `/scenarios/${s.id}` ? "page" : undefined}>{copyFor(s.id, s).title}</Link>
          ))}
          <Link href="/#upload">Your own code</Link>
        </nav>
        {model !== undefined && <span className={`status ${model ? "" : "off"}`} title={model ? "AI model that answered last" : "The API is not reachable"}>{model ?? "API offline"}</span>}
      </div>
    </header>
  );
}
