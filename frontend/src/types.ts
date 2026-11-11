export type VerdictLabel = "primary" | "chronic" | "rejected" | "inconclusive";

export interface Config {
  engine: string;
  agentic: boolean;
  provider: string;
  model: string;
  default_dataset: string;
  datasets: string[];
  sla_response_minutes: number;
  min_followups: number;
}

export interface PeriodMetrics {
  month: string;
  leads: number;
  won: number;
  conversion_rate: number;
  revenue: number;
  currency: string;
  median_response_minutes?: number;
  share_with_second_followup?: number;
}

export interface Comparison {
  current: PeriodMetrics;
  baseline: PeriodMetrics;
  conversion_change_points: number;
  conversion_change_relative: number | null;
  revenue_change_relative: number | null;
  lead_volume_change_relative: number;
  p_value: number;
}

export interface SeriesPoint {
  date: string;
  leads: number;
  won: number;
  rate_7d: number | null;
}

export interface Changepoint {
  date: string;
  rate_before: number;
  rate_after: number;
}

export interface Signal {
  dimension: string;
  title: string;
  label: VerdictLabel;
  confidence: number;
  headline: string;
}

export interface HealthComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  detail: string;
}

export interface ModelCard {
  trained: boolean;
  algorithm?: string;
  rows?: number;
  cv_auc?: number;
  cv_brier?: number;
  base_rate?: number;
  drivers?: { feature: string; importance: number }[];
}

export interface DatasetInfo {
  name: string;
  leads: number;
  orders: number;
  conversations: number;
  documents: string[];
  months: string[];
  currency: string;
  dimensions: { name: string; label: string; segments: string[] }[];
}

export interface Overview {
  dataset: DatasetInfo;
  current: string;
  baseline: string;
  current_label: string;
  baseline_label: string;
  comparison: Comparison;
  health: { score: number; components: HealthComponent[] };
  series: SeriesPoint[];
  changepoint: Changepoint | null;
  signals: Signal[];
  model: ModelCard;
  documents: { document: string; sections: string[] }[];
}

export interface Evidence {
  kind: "metric" | "conversation" | "policy" | "model";
  direction: "supports" | "contradicts" | "context";
  text: string;
  source: string;
}

export interface Impact {
  points: number | null;
  orders: number | null;
  revenue: number | null;
  basis: string;
}

export interface Segment {
  segment: string;
  leads: number;
  conversion_rate: number | null;
  baseline_share: number;
  current_share: number;
}

export interface Hypothesis {
  id: string;
  title: string;
  statement: string;
  dimension: string | null;
  verdict: { label: VerdictLabel; confidence: number };
  reasoning: string;
  evidence: Evidence[];
  impact: Impact | null;
  factor: { label: string; segments: Segment[] } | null;
}

export interface Recommendation {
  id: string;
  title: string;
  rationale: string;
  hypothesis_id: string | null;
  effort: "low" | "medium" | "high";
  impact: Impact | null;
  action: { type: string; label: string; payload: Record<string, unknown> } | null;
}

export interface Report {
  id: string;
  dataset: string;
  question: string;
  engine: string;
  current: string;
  baseline: string;
  situation: { comparison: Comparison; current_label: string; baseline_label: string };
  summary: string;
  hypotheses: Hypothesis[];
  recommendations: Recommendation[];
  stats: {
    leads_examined: number;
    tool_calls: number;
    llm_calls: number;
    input_tokens: number;
    output_tokens: number;
    duration_seconds: number;
  };
  created_at: string;
}

export interface TraceEvent {
  seq: number;
  at: string;
  agent: string;
  kind: "stage" | "note" | "tool" | "hypothesis" | "verdict" | "recommendation" | "done" | "error";
  title: string;
  detail: Record<string, any> | null;
}

export interface ActionRecord {
  id: string;
  investigation_id: string;
  recommendation_id: string;
  title: string;
  type: "alert_rule" | "followup_tasks" | "manager_note";
  label: string;
  payload: Record<string, any>;
  status: "pending" | "executed" | "rejected";
  created_at: string;
  decided_at: string | null;
  result: { summary: string } | null;
}

export interface OutboxItem {
  id: string;
  action_id: string;
  kind: "task" | "alert_rule" | "note";
  lead_id: string | null;
  title: string;
  body: string | null;
  due_at: string | null;
  created_at: string;
}

export interface InvestigationSummary {
  id: string;
  dataset: string;
  question: string;
  engine: string;
  status: "running" | "complete" | "failed";
  error: string | null;
  created_at: string;
}

export interface InvestigationRecord extends InvestigationSummary {
  report: Report | null;
  events: TraceEvent[];
  actions: ActionRecord[];
}
