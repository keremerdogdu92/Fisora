// Summary: Formats read-only accounting amounts without changing canonical numeric values.
function formatReadOnlyAmount(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "-";
  if (!/^[+-]?\d+(?:[.,]\d+)?$/.test(raw)) return raw;
  if (raw.includes(".") && raw.includes(",")) return raw;

  const negative = raw.startsWith("-");
  const unsigned = raw.replace(/^[+-]/, "");
  const separator = unsigned.includes(",") ? "," : ".";
  const [integerRaw, fractionRaw = ""] = unsigned.split(separator);
  if (fractionRaw.length > 2) return raw;

  const integer = integerRaw.replace(/^0+(?=\d)/, "") || "0";
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const fraction = fractionRaw.padEnd(2, "0");
  return `${negative ? "-" : ""}${grouped},${fraction}`;
}

module.exports = { formatReadOnlyAmount };
