import type { DivisionsReply } from "@/types";

// Paths are relative to the page, so they work at /new/ now and at / after the swap (DAR-634).
const API = new URL("../api/", document.baseURI).pathname;

export async function fetchDivisions(): Promise<DivisionsReply> {
  const res = await fetch(API + "divisions");
  if (!res.ok) throw new Error(`divisions: ${res.status}`);
  return res.json();
}

export function apiPath(name: string): string {
  return API + name;
}
