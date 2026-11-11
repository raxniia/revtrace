import { api } from "../api";
import { dateTime } from "../format";
import { go, useLoad } from "../hooks";

export function InvestigationsPage({ dataset }: { dataset: string }) {
  const { data, error } = useLoad(() => api.investigations(dataset), [dataset]);
  if (error) return <p className="notice error">{error}</p>;
  return (
    <>
      <header>
        <h1>Investigations</h1>
        <p className="lede">Every question asked about {dataset}, with the evidence kept.</p>
      </header>
      <section className="sheet">
        {!data ? (
          <p className="empty">Loading…</p>
        ) : data.length === 0 ? (
          <p className="empty">
            No investigations yet. <a href="#/">Ask the first question</a>.
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Question</th>
                <th>Run on</th>
                <th>Status</th>
                <th>Asked</th>
              </tr>
            </thead>
            <tbody>
              {data.map((item) => (
                <tr key={item.id} className="link" onClick={() => go(`/investigations/${item.id}`)}>
                  <td>
                    <a href={`#/investigations/${item.id}`}>{item.question}</a>
                  </td>
                  <td className="dim">{item.engine}</td>
                  <td>
                    <span className={`status ${item.status}`}>{item.status}</span>
                  </td>
                  <td className="dim">{dateTime(item.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
