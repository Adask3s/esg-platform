export const REPORT_SCOPES = [
  { value: "ESG", label: "Full ESG" },
  { value: "Environmental", label: "Environmental" },
  { value: "Social", label: "Social" },
  { value: "Governance", label: "Governance" },
];

export const REPORT_STANDARDS = [
  { value: "GRI", label: "GRI" },
  { value: "SASB", label: "SASB" },
  { value: "TCFD", label: "TCFD" },
];

export const VALIDATION_STANDARDS = REPORT_STANDARDS;

export function scopeFromTag(tag, fallback = "ESG") {
  const normalized = String(tag || "").trim().toLowerCase();
  if (normalized.startsWith("env") || normalized === "e") return "Environmental";
  if (normalized.startsWith("soc") || normalized === "s") return "Social";
  if (normalized.startsWith("gov") || normalized === "g") return "Governance";
  if (normalized === "esg") return "ESG";
  return fallback;
}

export function mapTagToApi(tag) {
  return scopeFromTag(tag, "ESG");
}

export function formatIndicator(indicator) {
  if (!indicator) return "Metric extraction in progress.";
  const name = indicator.nazwa || "Indicator";
  const value = indicator.wartosc ?? "-";
  const unit = indicator.jednostka ? ` ${indicator.jednostka}` : "";
  return `${name}: ${value}${unit}`;
}

export function filenameFromDisposition(disposition) {
  if (!disposition) return "raport_ESG.pdf";
  const utfMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utfMatch?.[1]) return decodeURIComponent(utfMatch[1]);
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i);
  return asciiMatch?.[1] || "raport_ESG.pdf";
}
