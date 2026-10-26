"use client";
import { useCallback, useEffect, useState } from "react";

// Keeps the last attack / repair result in sessionStorage so it survives moving between pages (the API does not store them).
export function useStored<T>(key: string): [T | null, (v: T | null) => void] {
  const [value, setValue] = useState<T | null>(null);
  useEffect(() => {
    try { const raw = sessionStorage.getItem(key); if (raw) setValue(JSON.parse(raw) as T); } catch { /* storage unavailable */ }
  }, [key]);
  const set = useCallback((v: T | null) => {
    setValue(v);
    try { if (v === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, JSON.stringify(v)); } catch { /* ignore */ }
  }, [key]);
  return [value, set];
}
