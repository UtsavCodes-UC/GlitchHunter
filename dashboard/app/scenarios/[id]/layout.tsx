"use client";
import { useParams } from "next/navigation";
import ScenarioTabs from "@/components/ScenarioTabs";

export default function ScenarioLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <h1 style={{ textTransform: "capitalize" }}>{id}</h1>
      <ScenarioTabs id={id} />
      {children}
    </>
  );
}
