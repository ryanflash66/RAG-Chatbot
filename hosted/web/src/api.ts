import type { DivisionsReply } from "@/types";

// Relative to the page, which is served at / (it was at /new/ until DAR-634).
const API = new URL("api/", document.baseURI).pathname;

export async function fetchDivisions(): Promise<DivisionsReply> {
  const res = await fetch(API + "divisions");
  if (!res.ok) throw new Error(`divisions: ${res.status}`);
  return res.json();
}

export function apiPath(name: string): string {
  return API + name;
}
