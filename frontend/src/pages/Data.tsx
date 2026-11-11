import { type FormEvent, useState } from "react";
import { api } from "../api";
import { count, pct } from "../format";
import { useLoad } from "../hooks";

interface Props {
  dataset: string;
  onUploaded: (name: string) => void;
}

export function DataPage({ dataset, onUploaded }: Props) {
  const { data, error } = useLoad(() => api.overview(dataset), [dataset]);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; failed: boolean } | null>(null);

  async function upload(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const created = await api.upload(name, files);
      setMessage({ text: `${created.name} is ready: ${count(created.leads)} leads across ${created.months.length} months.`, failed: false });
      onUploaded(created.name);
    } catch (reason) {
      setMessage({ text: (reason as Error).message, failed: true });
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="notice error">{error}</p>;
  if (!data) return <p className="empty">Loading…</p>;
  const { model } = data;
  const strongest = Math.max(...(model.drivers ?? []).map((d) => d.importance), 0.0001);

  return (
    <>
      <header>
        <h1>Data</h1>
        <p className="lede">What the agents can see: the records, the documents, and the model trained on them.</p>
      </header>

      <div className="grid2">
        <section className="sheet">
          <div className="sheet-head">
            <h2>{data.dataset.name}</h2>
          </div>
          <dl className="deflist">
            <dt>Leads</dt>
            <dd>{count(data.dataset.leads)}</dd>
            <dt>Orders</dt>
            <dd>{count(data.dataset.orders)}</dd>
            <dt>Conversations</dt>
            <dd>{count(data.dataset.conversations)}</dd>
            <dt>Months</dt>
            <dd>{data.dataset.months.join(", ")}</dd>
            <dt>Dimensions</dt>
            <dd>
              <div className="chips">
                {data.dataset.dimensions.map((d) => (
                  <span key={d.name} title={d.segments.join(", ")}>{d.label}</span>
                ))}
              </div>
            </dd>
          </dl>
        </section>

        <section className="sheet">
          <div className="sheet-head">
            <h2>Company documents</h2>
            <p>Searchable by the agents</p>
          </div>
          {data.documents.length === 0 ? (
            <p className="empty">No documents. Add .md or .txt files with a dataset to let agents check policies.</p>
          ) : (
            <dl className="deflist">
              {data.documents.map((doc) => (
                <div key={doc.document} style={{ display: "contents" }}>
                  <dt>{doc.document.split("—").pop()?.trim()}</dt>
                  <dd>{doc.sections.join(", ")}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section className="sheet">
          <div className="sheet-head">
            <h2>Conversion model</h2>
            <p>{model.trained ? model.algorithm : "Not trained"}</p>
          </div>
          {model.trained ? (
            <>
              <dl className="deflist">
                <dt>Cross-validated AUC</dt>
                <dd>{model.cv_auc}</dd>
                <dt>Brier score</dt>
                <dd>{model.cv_brier}</dd>
                <dt>Base conversion</dt>
                <dd>{pct(model.base_rate)}</dd>
                <dt>Training rows</dt>
                <dd>{count(model.rows ?? 0)}</dd>
              </dl>
              <ul className="gauges">
                {model.drivers!.slice(0, 6).map((driver) => (
                  <li key={driver.feature}>
                    <div className="row">
                      <span>{driver.feature.replace(/_/g, " ")}</span>
                      <span>{driver.importance.toFixed(3)}</span>
                    </div>
                    <div className="bar">
                      <i style={{ width: `${(driver.importance / strongest) * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
              <small className="empty">Permutation importance: AUC lost when the feature is shuffled.</small>
            </>
          ) : (
            <p className="empty">The model needs at least 400 leads with both won and lost outcomes.</p>
          )}
        </section>

        <section className="sheet">
          <div className="sheet-head">
            <h2>Add a dataset</h2>
          </div>
          <form onSubmit={upload}>
            <label className="field">
              Name
              <input type="text" value={name} onChange={(event) => setName(event.target.value)} required placeholder="Spring campaign" />
            </label>
            <label className="field">
              Files
              <input type="file" multiple required onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
              <small>
                leads.csv is required (lead_id, created_at, status). Optional: orders.csv, customers.csv,
                conversations.json, and policy documents as .md or .txt.
              </small>
            </label>
            <button className="btn" disabled={busy}>
              {busy ? "Adding…" : "Add dataset"}
            </button>
          </form>
          {message && <p className={`notice ${message.failed ? "error" : ""}`} style={{ marginTop: 14 }}>{message.text}</p>}
        </section>
      </div>
    </>
  );
}
