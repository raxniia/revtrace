import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { HypothesisSheet, ImpactLine } from "../components/HypothesisSheet";
import { Stamp } from "../components/Stamp";
import { count, dateTime, VERDICTS } from "../format";
import type { ActionRecord, InvestigationRecord, TraceEvent, VerdictLabel } from "../types";

export const fresh = new Set<string>();
const PACE_MS = 110;

function LogEntry({ event }: { event: TraceEvent }) {
  if (event.kind === "tool") {
    return (
      <li className="tool">
        <span className="who">{event.agent}</span> called <code>{event.title}</code>
        <small>{event.detail?.summary}</small>
      </li>
    );
  }
  if (event.kind === "hypothesis") {
    return (
      <li className="hypothesis-event">
        <span className="who">{event.agent}</span> proposed {event.detail?.id}: {event.title}
      </li>
    );
  }
  if (event.kind === "verdict") {
    const label = event.detail?.label as VerdictLabel;
    return (
      <li className="verdict">
        {event.detail?.id} {event.title}: <strong>{VERDICTS[label].stamp.toLowerCase()}</strong>, {event.detail?.confidence}/100
      </li>
    );
  }
  if (event.kind === "recommendation") {
    return (
      <li>
        <span className="who">{event.agent}</span> recommends: {event.title}
      </li>
    );
  }
  return <li className={event.kind}>{event.title}</li>;
}

interface Props {
  id: string;
  onDecided: () => void;
}

export function InvestigationPage({ id, onDecided }: Props) {
  const [record, setRecord] = useState<InvestigationRecord | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [live, setLive] = useState(false);
  const [justClosed, setJustClosed] = useState(false);
  const [error, setError] = useState("");
  const [deciding, setDeciding] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let timer = 0;
    setRecord(null);
    setEvents([]);
    setError("");
    setJustClosed(false);

    api
      .investigation(id)
      .then((loaded) => {
        if (cancelled) return;
        if (loaded.status !== "running" && !fresh.has(id)) {
          setRecord(loaded);
          setEvents(loaded.events);
          return;
        }
        setLive(true);
        const queue: TraceEvent[] = [];
        let ended = false;
        source = new EventSource(`/api/investigations/${id}/events`);
        source.onmessage = (message) => queue.push(JSON.parse(message.data));
        source.addEventListener("end", () => {
          ended = true;
          source?.close();
        });
        source.onerror = () => {
          ended = true;
          source?.close();
        };
        timer = window.setInterval(() => {
          const next = queue.shift();
          if (next) {
            setEvents((shown) => [...shown, next]);
          } else if (ended) {
            window.clearInterval(timer);
            fresh.delete(id);
            api.investigation(id).then((finished) => {
              if (cancelled) return;
              setRecord(finished);
              setLive(false);
              setJustClosed(true);
            });
          }
        }, PACE_MS);
      })
      .catch((reason: Error) => !cancelled && setError(reason.message));

    return () => {
      cancelled = true;
      source?.close();
      window.clearInterval(timer);
    };
  }, [id]);

  useEffect(() => {
    if (live && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events, live]);

  const drafts = useMemo(() => {
    const verdicts = new Map(events.filter((e) => e.kind === "verdict").map((e) => [e.detail?.id, e.detail]));
    return events
      .filter((e) => e.kind === "hypothesis")
      .map((e) => ({ id: e.detail?.id as string, title: e.title, statement: e.detail?.statement as string, verdict: verdicts.get(e.detail?.id) }));
  }, [events]);

  if (error) return <p className="notice error">{error}</p>;

  const report = live ? null : record?.report;
  const actions = new Map<string, ActionRecord>((record?.actions ?? []).map((a) => [a.recommendation_id, a]));
  const question = record?.question ?? events.find((e) => e.kind === "stage")?.detail?.question ?? "Investigation";

  async function decide(action: ActionRecord, approve: boolean) {
    setDeciding(action.id);
    try {
      await api.decide(action.id, approve);
      setRecord(await api.investigation(id));
      onDecided();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setDeciding("");
    }
  }

  return (
    <>
      <header>
        <p className="kicker">
          <a href="#/investigations">Investigations</a> / {id}
        </p>
        <h1>{question}</h1>
        {report && (
          <div className="case-meta">
            <span>{report.situation.current_label} against {report.situation.baseline_label}</span>
            <span>{count(report.stats.leads_examined)} leads examined</span>
            <span>{report.stats.tool_calls} tool calls</span>
            <span>{report.stats.llm_calls ? `${report.stats.llm_calls} model calls on ${report.engine}` : "statistical baseline, no model calls"}</span>
            <span>{report.stats.duration_seconds}s</span>
          </div>
        )}
        {live && (
          <div className="case-meta">
            <span><i className="pulse" />Agents at work</span>
          </div>
        )}
      </header>

      {record?.status === "failed" && <p className="notice error">The investigation stopped: {record.error}</p>}

      <div className="case">
        <div className="stack">
          {report && <p className="summary">{report.summary}</p>}

          {report
            ? report.hypotheses.map((hypothesis) => (
                <HypothesisSheet
                  key={hypothesis.id}
                  hypothesis={hypothesis}
                  currency={report.situation.comparison.current.currency}
                  periods={[report.situation.current_label, report.situation.baseline_label]}
                  fresh={justClosed}
                />
              ))
            : drafts.map((draft) => (
                <article className="sheet hypothesis" key={draft.id}>
                  <div className="hyp-head">
                    <div>
                      <span className="hyp-id">{draft.id}</span>
                      <h3>{draft.title}</h3>
                      <p>{draft.statement}</p>
                    </div>
                    <Stamp label={draft.verdict ? (draft.verdict.label as VerdictLabel) : "pending"} fresh />
                  </div>
                </article>
              ))}

          {report && report.recommendations.length > 0 && (
            <section className="sheet">
              <div className="sheet-head">
                <h2>Recommended actions</h2>
                <p>Nothing runs until you approve it</p>
              </div>
              {report.recommendations.map((rec) => {
                const action = actions.get(rec.id);
                return (
                  <div className="rec" key={rec.id}>
                    <div>
                      <h3>{rec.title}</h3>
                      <p>{rec.rationale}</p>
                      <ImpactLine impact={rec.impact} currency={report.situation.comparison.current.currency} />
                      <div className="tags">
                        <span>{rec.effort} effort</span>
                        {rec.hypothesis_id && <span>from {rec.hypothesis_id}</span>}
                      </div>
                    </div>
                    {action && (
                      <div className="decide">
                        {action.status === "pending" ? (
                          <>
                            <button className="btn" disabled={deciding === action.id} onClick={() => decide(action, true)}>
                              {action.label}
                            </button>
                            <button className="btn quiet" disabled={deciding === action.id} onClick={() => decide(action, false)}>
                              Decline
                            </button>
                          </>
                        ) : (
                          <span className={`outcome ${action.status === "rejected" ? "declined" : ""}`}>
                            {action.status === "executed" ? action.result?.summary : "Declined"}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </section>
          )}
        </div>

        <aside className="sheet log" ref={logRef} aria-label="Case log">
          <h2>Case log</h2>
          {record && !live && <p className="kicker" style={{ margin: "4px 0 0" }}>{dateTime(record.created_at)}</p>}
          <ol>
            {events.map((event) => (
              <LogEntry key={event.seq} event={event} />
            ))}
          </ol>
        </aside>
      </div>
    </>
  );
}
