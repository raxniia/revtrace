import type {
  ActionRecord,
  Config,
  DatasetInfo,
  InvestigationRecord,
  InvestigationSummary,
  OutboxItem,
  Overview,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  config: () => request<Config>("/api/config"),
  overview: (dataset: string) => request<Overview>(`/api/overview?dataset=${encodeURIComponent(dataset)}`),
  investigations: (dataset: string) =>
    request<InvestigationSummary[]>(`/api/investigations?dataset=${encodeURIComponent(dataset)}`),
  investigation: (id: string) => request<InvestigationRecord>(`/api/investigations/${id}`),
  investigate: (question: string, dataset: string) =>
    request<{ id: string }>("/api/investigations", json({ question, dataset })),
  actions: () => request<{ actions: ActionRecord[]; outbox: OutboxItem[] }>("/api/actions"),
  decide: (id: string, approve: boolean) => request<ActionRecord>(`/api/actions/${id}/decision`, json({ approve })),
  upload: (name: string, files: File[]) => {
    const form = new FormData();
    form.append("name", name);
    files.forEach((file) => form.append("files", file));
    return request<DatasetInfo>("/api/datasets", { method: "POST", body: form });
  },
};
