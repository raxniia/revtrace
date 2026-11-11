import { useState } from "react";
import { api } from "../api";
import { dateTime } from "../format";
import { useLoad } from "../hooks";
import type { ActionRecord } from "../types";

function Payload({ action }: { action: ActionRecord }) {
  const { payload } = action;
  if (action.type === "followup_tasks") {
    return (
      <div className="payload">
        {payload.lead_ids.length} qualified leads touched once in the last two weeks, due within {payload.due_in_hours} hours.
        <q>{payload.message}</q>
      </div>
    );
  }
  if (action.type === "alert_rule") {
    return (
      <div className="payload">
        Notify the {payload.notify} whenever a new lead has waited {payload.threshold_minutes} minutes without a reply.
      </div>
    );
  }
  return <div className="payload">{payload.note || payload.subject}</div>;
}

export function ActionsPage({ onDecided }: { onDecided: () => void }) {
  const { data, error, reload } = useLoad(() => api.actions(), []);
  const [busy, setBusy] = useState("");
  const [failure, setFailure] = useState("");

  if (error) return <p className="notice error">{error}</p>;
  if (!data) return <p className="empty">Loading…</p>;

  const pending = data.actions.filter((a) => a.status === "pending");
  const decided = data.actions.filter((a) => a.status !== "pending");
  const tasks = data.outbox.filter((o) => o.kind === "task");

  async function decide(action: ActionRecord, approve: boolean) {
    setBusy(action.id);
    setFailure("");
    try {
      await api.decide(action.id, approve);
      reload();
      onDecided();
    } catch (reason) {
      setFailure((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <header>
        <h1>Actions</h1>
        <p className="lede">Agents propose. A person approves. Nothing reaches a customer or a colleague before that.</p>
      </header>
      {failure && <p className="notice error">{failure}</p>}

      <section className="sheet">
        <div className="sheet-head">
          <h2>Waiting for your decision</h2>
          <p>{pending.length} pending</p>
        </div>
        {pending.length === 0 && <p className="empty">Nothing is waiting. Run an investigation to get proposals.</p>}
        {pending.map((action) => (
          <div className="rec" key={action.id}>
            <div>
              <h3>{action.title}</h3>
              <Payload action={action} />
              <div className="tags">
                <a href={`#/investigations/${action.investigation_id}`}>See the investigation</a>
                <span>proposed {dateTime(action.created_at)}</span>
              </div>
            </div>
            <div className="decide">
              <button className="btn" disabled={busy === action.id} onClick={() => decide(action, true)}>
                {action.label}
              </button>
              <button className="btn quiet" disabled={busy === action.id} onClick={() => decide(action, false)}>
                Decline
              </button>
            </div>
          </div>
        ))}
      </section>

      {decided.length > 0 && (
        <section className="sheet">
          <div className="sheet-head">
            <h2>Decided</h2>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Outcome</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {decided.map((action) => (
                <tr key={action.id}>
                  <td>{action.title}</td>
                  <td>
                    <span className={`status ${action.status}`}>
                      {action.status === "executed" ? action.result?.summary : "Declined"}
                    </span>
                  </td>
                  <td className="dim">{action.decided_at && dateTime(action.decided_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tasks.length > 0 && (
        <section className="sheet">
          <div className="sheet-head">
            <h2>Follow-up tasks created</h2>
            <p>{tasks.length} in the task queue</p>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Lead</th>
                <th>Message to send</th>
                <th>Due</th>
              </tr>
            </thead>
            <tbody>
              {tasks.slice(0, 8).map((task) => (
                <tr key={task.id}>
                  <td className="dim">{task.lead_id}</td>
                  <td>{task.body}</td>
                  <td className="dim">{task.due_at && dateTime(task.due_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {tasks.length > 8 && <p className="empty">and {tasks.length - 8} more.</p>}
        </section>
      )}
    </>
  );
}
