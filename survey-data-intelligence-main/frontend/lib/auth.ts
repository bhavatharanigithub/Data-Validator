"use client";

import type { Role } from "./api/types";

const KEY = "sv.session.profile";

export interface SessionProfile {
  username: string;
  role: Role;
  display_name?: string;
  demo?: boolean;
}

export function readSession(): SessionProfile | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionProfile;
  } catch {
    return null;
  }
}

export function writeSession(session: SessionProfile): void {
  window.sessionStorage.setItem(KEY, JSON.stringify(session));
}

export function clearSession(): void {
  window.sessionStorage.removeItem(KEY);
}
