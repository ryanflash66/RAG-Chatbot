// Wording and link checks shared by the panels (and the "Searched N passages in M
// documents" line under each answer, which uses the same counts).

export function count(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function documentsText(n: number, total: number): string {
  return n < total ? `${n} of ${total} documents` : count(n, "document");
}

/**
 * The URL when it is http(s), else null. The manuals are public NCDOT PDFs
 * (divrag/divisions.py), and this keeps a javascript: or data: URL from ever
 * becoming a clickable link.
 */
export function webUrl(url: string | null | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}
