"use client";
import { useCallback, useEffect, useState } from "react";
import { getInvariants } from "./api";
import { useStored } from "./useStored";
import type { AttackResponse, Invariant, RepairResponse } from "./types";

export interface Stage { key: string; label: string; done: boolean; detail: string }

// Everything a page needs to know about one scenario: rules from the API, last attack / repair from sessionStorage, stage status.
export function useScenario(id: string) {
  const [invariants, setInvariants] = useState<Invariant[] | null>(null);
  const [attack, setAttack] = useStored<AttackResponse>(`gh:attack:${id}`);
  const [repair, setRepair] = useStored<RepairResponse>(`gh:repair:${id}`);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setInvariants(await getInvariants(id)); setLoadError(null); }
    catch (e) { setLoadError((e as Error).message); setInvariants([]); }
  }, [id]);
  useEffect(() => { refresh(); }, [refresh]);

  const inv = invariants ?? [];
  const approved = inv.filter((i) => i.status === "approved").length;
  const stages: Stage[] = [
    { key: "propose", label: "Propose", done: inv.some((i) => i.source === "llm"), detail: `${inv.filter((i) => i.source === "llm").length} AI-proposed rules` },
    { key: "filter", label: "Filter", done: inv.some((i) => i.stats?.sequential_trials), detail: `${inv.filter((i) => i.status === "dropped").length} dropped, ${inv.filter((i) => i.status === "uninformative").length} uninformative, ${approved} approved` },
    { key: "attack", label: "Attack", done: attack !== null, detail: attack ? `${attack.summary.trials_with_violation} of ${attack.summary.trials} trials violated a rule` : "not run yet" },
    { key: "explain", label: "Explain", done: !!attack?.first_failing_trial, detail: attack?.first_failing_trial ? "failing run saved" : "needs a failing run" },
    { key: "repair", label: "Repair", done: repair !== null, detail: repair ? (repair.accepted ? "a fix was accepted" : "no fix accepted") : "not run yet" },
  ];
  return { invariants, setInvariants, attack, setAttack, repair, setRepair, loadError, refresh, stages, approved };
}
