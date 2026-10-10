"use client";

import { useCallback, useEffect, useState } from "react";

/** Workspace accent: a per-device preference (Settings → Appearance), not account data. */
export const ACCENTS = [
  { key: "forest", label: "Forest", swatch: "#14532d" },
  { key: "ocean", label: "Ocean", swatch: "#1e3a8a" },
  { key: "plum", label: "Plum", swatch: "#6b21a8" },
  { key: "ember", label: "Ember", swatch: "#9a3412" },
] as const;

export type Accent = (typeof ACCENTS)[number]["key"];

const STORAGE_KEY = "aurevia.accent";
const DEFAULT: Accent = "forest";

function isAccent(value: string | null): value is Accent {
  return ACCENTS.some((a) => a.key === value);
}

function stored(): Accent {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isAccent(value) ? value : DEFAULT;
  } catch {
    return DEFAULT; // storage blocked (private window): use the default
  }
}

/** Runs before first paint (inline in <head>) so the page never flashes the wrong accent. */
export const ACCENT_BOOT_SCRIPT = `try{var a=localStorage.getItem("${STORAGE_KEY}");if(a)document.documentElement.dataset.accent=a}catch(e){}`;

export function useAccent(): [Accent, (accent: Accent) => void] {
  const [accent, setState] = useState<Accent>(DEFAULT);
  useEffect(() => setState(stored()), []);
  const setAccent = useCallback((next: Accent) => {
    document.documentElement.dataset.accent = next;
    setState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // not remembered this time; the page still re-tints
    }
  }, []);
  return [accent, setAccent];
}
