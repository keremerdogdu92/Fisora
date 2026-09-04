// File: frontend/app/shared/components/document-viewers/document-inspector-types.ts
// Summary: Defines reusable source-focus contracts shared by document viewers and the accountant ledger.

export type DocumentSourceFocus = {
  documentId: string;
  key: string;
  pinned: boolean;
  sourcePosition?: string;
  sourceText: string;
};

export function documentSourceFocusKey(documentId: string, sourceText: string, sourcePosition: string | undefined, index: number) {
  const normalizedText = String(sourceText || "").replace(/\s+/g, " ").trim();
  return `${documentId}::${String(sourcePosition || index + 1).trim()}::${normalizedText}`;
}
