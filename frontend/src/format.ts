export const pct = (value: number | null | undefined, digits = 1) =>
  value == null ? "n/a" : `${(value * 100).toFixed(digits)}%`;

export const signedPct = (value: number | null | undefined) =>
  value == null ? "n/a" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(0)}%`;

export const count = (value: number) => Math.round(value).toLocaleString("en-US").replace(/,/g, " ");

export function money(value: number, currency: string) {
  const abs = Math.abs(value);
  const text = abs >= 1e6 ? `${(value / 1e6).toFixed(1)} M` : abs >= 1e4 ? `${Math.round(value / 1e3)} k` : count(value);
  return `${text} ${currency}`.trim();
}

export const monthName = (month: string) =>
  new Date(`${month}-01T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export const VERDICTS = {
  primary: { stamp: "Cause", phrase: "Confirmed as a cause" },
  chronic: { stamp: "Standing leak", phrase: "A leak, but not what changed" },
  rejected: { stamp: "Ruled out", phrase: "Ruled out" },
  inconclusive: { stamp: "Untested", phrase: "Could not be tested" },
} as const;

export const grade = (confidence: number) => (confidence >= 70 ? "strong" : confidence >= 40 ? "moderate" : "weak");
