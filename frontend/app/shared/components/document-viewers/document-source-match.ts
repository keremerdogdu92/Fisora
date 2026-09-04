// File: frontend/app/shared/components/document-viewers/document-source-match.ts
// Summary: Provides deterministic tokenization and exact source-text sequence matching for document viewers.

export type SourceToken = {
  end: number;
  start: number;
  value: string;
};

export function tokenizeSourceText(value: string): SourceToken[] {
  const text = String(value || "");
  const tokens: SourceToken[] = [];
  const matcher = /[\p{L}\p{N}]+/gu;
  let match: RegExpExecArray | null = matcher.exec(text);
  while (match) {
    tokens.push({
      end: match.index + match[0].length,
      start: match.index,
      value: match[0].normalize("NFKC").toLocaleLowerCase("tr-TR"),
    });
    match = matcher.exec(text);
  }
  return tokens;
}

export function findTokenSequence(haystack: string[], needle: string[], fromIndex = 0) {
  if (!needle.length || haystack.length < needle.length) return null;
  const lastStart = haystack.length - needle.length;
  for (let start = Math.max(0, fromIndex); start <= lastStart; start += 1) {
    let matches = true;
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (haystack[start + offset] !== needle[offset]) {
        matches = false;
        break;
      }
    }
    if (matches) return { end: start + needle.length - 1, start };
  }
  return null;
}

export function sourceTokenValues(value: string) {
  return tokenizeSourceText(value).map((token) => token.value);
}
