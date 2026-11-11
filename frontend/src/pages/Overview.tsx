import { type FormEvent, useState } from "react";
import { api } from "../api";
import { HealthDial } from "../components/HealthDial";
import { Stamp } from "../components/Stamp";
import { TraceChart } from "../components/TraceChart";
import { count, money, pct, signedPct } from "../format";
import { go, useLoad } from "../hooks";
import { fresh } from "./Investigation";

export function OverviewPage({ dataset }: { dataset: string }) {
  const { data, error } = useLoad(() => api.overview(dataset), [dataset]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");

  if (error) return <p className="notice error">{error}</p>;
  if (!data) return <p className="empty">Loading {dataset}…</p>;

  const { comparison, current_label, baseline_label } = data;
  const { current, baseline } = comparison;
  const fell = comparison.conversion_change_points < 0;
  const month = current_label.split(" ")[0];
  const prompts = [
    `Why did conversion ${fell ? "drop" : "change"} in ${month}?`,
    "Is price the reason we are losing deals?",
    "Which leads are we failing to follow up?",
  ];

  async function ask(text: string) {
    if (!text.trim() || busy) return;
    setBusy(true);
    setFailure("");
    try {
      const { id } = await api.investigate(text, dataset);
      fresh.add(id);
      go(`/investigations/${id}`);
    } catch (reason) {
      setFailure((reason as Error).message);
      setBusy(false);
    }
  }

  const delta = (value: number | null) => (
    <small className={value != null && value < 0 ? "down" : "up"}>{signedPct(value)}</small>
  );

  return (
    <>
      <header>
        <p className="kicker">
          {data.dataset.name}, {current_label} against {baseline_label}
        </p>
        <h1>
          Conversion {fell ? "fell" : "rose"} from {pct(baseline.conversion_rate)} to {pct(current.conversion_rate)} in {month}.
        </h1>
        <p className="lede">
          {count(current.leads)} leads came in, {signedPct(comparison.lead_volume_change_relative)} on {baseline_label.split(" ")[0]},
          and {count(current.won)} became sales. Ask why, and the agents will test each explanation against the data.
        </p>
      </header>

      <section>
        <form
          className="ask"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            ask(question || prompts[0]);
          }}
        >
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={prompts[0]}
            aria-label="Question to investigate"
          />
          <button className="btn" disabled={busy}>
            {busy ? "Starting…" : "Investigate"}
          </button>
        </form>
        <div className="prompts">
          {prompts.slice(1).map((prompt) => (
            <button key={prompt} type="button" onClick={() => ask(prompt)}>
              {prompt}
            </button>
          ))}
        </div>
        {failure && <p className="notice error" style={{ marginTop: 12 }}>{failure}</p>}
      </section>

      <section className="sheet">
        <div className="sheet-head">
          <h2>Conversion rate, seven-day rolling</h2>
          <p>{count(data.dataset.leads)} leads since {data.series[0].date}</p>
        </div>
        <TraceChart series={data.series} changepoint={data.changepoint} current={data.current} baseline={data.baseline} />
        <dl className="figures">
          <div className="figure">
            <dt>Leads</dt>
            <dd>{count(current.leads)}{delta(comparison.lead_volume_change_relative)}</dd>
          </div>
          <div className="figure">
            <dt>Sales</dt>
            <dd>{count(current.won)}{delta(current.won / baseline.won - 1)}</dd>
          </div>
          <div className="figure">
            <dt>Revenue</dt>
            <dd>{money(current.revenue, current.currency)}{delta(comparison.revenue_change_relative)}</dd>
          </div>
          {current.median_response_minutes != null && (
            <div className="figure">
              <dt>Median first reply</dt>
              <dd>
                {Math.round(current.median_response_minutes)} min
                <small>was {Math.round(baseline.median_response_minutes ?? 0)}</small>
              </dd>
            </div>
          )}
        </dl>
      </section>

      <div className="split">
        <section className="sheet">
          <div className="sheet-head">
            <h2>What already stands out</h2>
            <p>Statistical scan, before any investigation</p>
          </div>
          {data.signals.length === 0 ? (
            <p className="empty">Nothing separates {current_label} from {baseline_label} yet.</p>
          ) : (
            <ul className="signals">
              {data.signals.map((signal) => (
                <li key={signal.dimension}>
                  <Stamp label={signal.label} />
                  <div>
                    <h3>{signal.title}</h3>
                    <p>{signal.headline}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="sheet">
          <div className="sheet-head">
            <h2>Sales health</h2>
            <p>{current_label}</p>
          </div>
          <HealthDial score={data.health.score} components={data.health.components} />
        </section>
      </div>
    </>
  );
}
