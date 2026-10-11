import type { Term } from "./types";

// Scripts written without spaces between words (Thai, Lao, Myanmar, Khmer, kana, CJK, Hangul) — same set
// as the backend's NO_SPACE_CHARS, so highlighting matches what the agents were told.
const NO_SPACE = "฀-໿က-႟ក-៿぀-ヿ㐀-䶿一-鿿가-힯豈-﫿";
const SPACED_WORD = `(?:(?![${NO_SPACE}])[\\p{L}\\p{N}\\p{M}_])`;
const spacedWord = new RegExp(`^${SPACED_WORD}$`, "u");
export const noSpaceScript = new RegExp(`[${NO_SPACE}]`, "u");

const cache = new Map<string, RegExp>();

/** Whole words in spaced scripts, plain substrings in CJK/Thai (mirrors backend `text.term_pattern`). */
function pattern(term: string, caseSensitive: boolean): RegExp {
  const key = `${caseSensitive ? 1 : 0}${term}`;
  let re = cache.get(key);
  if (!re) {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const left = spacedWord.test(term.slice(0, 1)) ? `(?<!${SPACED_WORD})` : "";
    const right = spacedWord.test(term.slice(-1)) ? `(?!${SPACED_WORD})` : "";
    re = new RegExp(left + escaped + right, caseSensitive ? "gu" : "giu");
    cache.set(key, re);
  }
  re.lastIndex = 0;
  return re;
}

export interface TermHit {
  start: number;
  end: number;
  term: Term;
}

/** Non-overlapping term occurrences in `text`, longest first where they overlap. */
export function findTerms(text: string, terms: Term[]): TermHit[] {
  const hits: TermHit[] = [];
  for (const term of terms) {
    if (!term.source) continue;
    for (const m of text.matchAll(pattern(term.source, term.case_sensitive))) {
      hits.push({ start: m.index, end: m.index + m[0].length, term });
    }
  }
  hits.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start));
  const out: TermHit[] = [];
  let pos = 0;
  for (const h of hits) {
    if (h.start >= pos) {
      out.push(h);
      pos = h.end;
    }
  }
  return out;
}
