const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Locate a citation quote in the chunk text. The verifier matches on normalised text, so allow any
 * run of whitespace (line breaks from PDF extraction) between words and ignore case.
 */
export function findQuote(text: string, quote: string): [number, number] | null {
  const exact = text.indexOf(quote);
  if (exact >= 0) return [exact, exact + quote.length];
  const words = quote.normalize("NFKC").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const match = new RegExp(words.map(escape).join("\\s+"), "iu").exec(text.normalize("NFKC"));
  return match ? [match.index, match.index + match[0].length] : null;
}
