import { VERDICTS } from "../format";
import type { VerdictLabel } from "../types";

export function Stamp({ label, fresh = false }: { label: VerdictLabel | "pending"; fresh?: boolean }) {
  if (label === "pending") return <span className="stamp pending">Under investigation</span>;
  return <span className={`stamp ${label}${fresh ? " fresh" : ""}`}>{VERDICTS[label].stamp}</span>;
}
