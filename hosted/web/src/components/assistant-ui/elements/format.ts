// Text for the answer's steps and footer, as the old page wrote it (public/js/render.js,
// steps.js, docs.js).

export function seconds(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** "nvidia/nemotron-3-ultra-550b-a55b:free" -> "nemotron-3-ultra-550b-a55b"; the full id is the tooltip. */
export function modelName(id: string): string {
  return String(id).replace(/^[^/]*\//, "").replace(/:free$/, "");
}

export function count(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "Searched 412 passages in 1 document." / "… in 1 of 2 documents." */
export function searchedText(searched: { documents: number; passages: number }, total: number): string {
  const documents = searched.documents < total ? `${searched.documents} of ${total} documents` : count(searched.documents, "document");
  return `Searched ${count(searched.passages, "passage")} in ${documents}.`;
}

/**
 * The answer's [n] markers as Markdown links to #cite-n, which the answer's link
 * component draws as citation buttons. A marker without a source (n out of 1..sources)
 * is dropped, as the old page did.
 */
export function linkCitations(text: string, sources: number): string {
  return text.replace(/\[(\d+)\]/g, (_, digits: string) => {
    const n = Number(digits);
    return n >= 1 && n <= sources ? `[${n}](#cite-${n})` : "";
  });
}

export const CITE_PREFIX = "#cite-";
