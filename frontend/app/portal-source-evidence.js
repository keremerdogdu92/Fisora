// File: frontend/app/portal-source-evidence.js
// Summary: Formats source-evidence labels without inferring accounting semantics from source linkage alone.

function vatGroupEvidenceText(line) {
  const sourceLineNumbers = Array.isArray(line?.source_line_numbers)
    ? line.source_line_numbers.filter((value) => Number.isInteger(value) && value > 0)
    : [];
  if (!line?.vat_group_id && !sourceLineNumbers.length) return "";

  const rate = String(line?.vat_group_id || "").split("|")[2] || String(line?.tax_rate || "").trim();
  const sourceText = sourceLineNumbers.length
    ? sourceLineNumbers.join(", ")
    : (line?.contributing_line_ids || []).map((_, index) => index + 1).join(", ");

  if (!rate) return sourceText ? `Kaynak: Fatura satırları ${sourceText}` : "";
  return sourceText ? `Kaynak: KDV %${rate} · Fatura satırları ${sourceText}` : `Kaynak: KDV %${rate}`;
}

module.exports = { vatGroupEvidenceText };
