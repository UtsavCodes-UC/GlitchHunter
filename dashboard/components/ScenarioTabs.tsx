"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function ScenarioTabs({ id }: { id: string }) {
  const path = usePathname();
  const tabs = [
    { href: `/scenarios/${id}`, label: "Overview" },
    { href: `/scenarios/${id}/invariants`, label: "Rules" },
    { href: `/scenarios/${id}/attack`, label: "Attack" },
    { href: `/scenarios/${id}/repair`, label: "Repair" },
  ];
  return (
    <nav className="tabs" aria-label="Scenario sections">
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} className={`tab ${path === t.href ? "active" : ""}`}>{t.label}</Link>
      ))}
    </nav>
  );
}
