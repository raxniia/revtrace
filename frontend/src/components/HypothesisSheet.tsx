import { grade, money, pct, VERDICTS } from "../format";
import type { Evidence, Hypothesis, Impact } from "../types";
import { Marked } from "./Marked";
import { Stamp } from "./Stamp";

const KINDS = { metric: "Numbers", conversation: "Customers", policy: "Policy", model: "Model" };
const SIGNS = { supports: "+", contradicts: "−", context: "·" };

export function ImpactLine({ impact, currency }: { impact: Impact | null; currency: string }) {
  if (!impact?.revenue) return null;
  return (
    <p className="impact">
      At stake: <strong>about {Math.round(impact.orders ?? 0)} orders</strong>, roughly{" "}
      <strong>{money(impact.revenue, currency)}</strong> a month ({impact.basis}).
    </p>
  );
}

function EvidenceRow({ item }: { item: Evidence }) {
  const quoted = item.kind === "conversation" && item.direction === "context";
  return (
    <li className={item.direction}>
      <span className="sign" title={item.direction}>{SIGNS[item.direction]}</span>
      <span className="kind">{KINDS[item.kind]}</span>
      <span>
        <span className={quoted ? "quote" : undefined}>
          <Marked text={item.text} />
        </span>
        {(item.kind === "policy" || quoted) && item.source && <cite>{item.source}</cite>}
      </span>
    </li>
  );
}

interface Props {
  hypothesis: Hypothesis;
  currency: string;
  periods: [string, string];
  fresh: boolean;
}

export function HypothesisSheet({ hypothesis, currency, periods, fresh }: Props) {
  const { verdict, factor } = hypothesis;
  const widest = factor ? Math.max(...factor.segments.flatMap((s) => [s.baseline_share, s.current_share])) : 1;
  return (
    <article className={`sheet hypothesis ${verdict.label}`}>
      <div className="hyp-head">
        <div>
          <span className="hyp-id">{hypothesis.id}</span>
          <h3>{hypothesis.title}</h3>
          <p>{hypothesis.statement}</p>
        </div>
        <Stamp label={verdict.label} fresh={fresh} />
      </div>
      {verdict.label !== "inconclusive" && (
        <div className="meter">
          <div className="track" aria-hidden="true">
            <i style={{ width: `${verdict.confidence}%` }} />
            <b style={{ left: "40%" }} />
            <b style={{ left: "70%" }} />
          </div>
          <span>
            Evidence it caused the change: <strong>{verdict.confidence}/100</strong>, {grade(verdict.confidence)}
          </span>
        </div>
      )}
      <p className="reasoning">{hypothesis.reasoning || VERDICTS[verdict.label].phrase}</p>
      {hypothesis.evidence.length > 0 && (
        <ul className="evidence">
          {hypothesis.evidence.map((item, i) => (
            <EvidenceRow key={i} item={item} />
          ))}
        </ul>
      )}
      {factor && verdict.label !== "rejected" && (
        <table className="segments">
          <caption>
            Leads by {factor.label}{" "}
            <span className="legend">
              <span><i />{periods[1]}</span>
              <span><i className="now" />{periods[0]}</span>
            </span>
          </caption>
          <thead>
            <tr>
              <th>Segment</th>
              <th>Share of leads</th>
              <th className="num">Before</th>
              <th className="num">Now</th>
              <th className="num">Converts at</th>
            </tr>
          </thead>
          <tbody>
            {factor.segments.map((segment) => (
              <tr key={segment.segment}>
                <td>{segment.segment}</td>
                <td>
                  <div className="pair">
                    <i style={{ width: `${(segment.baseline_share / widest) * 100}%` }} />
                    <i style={{ width: `${(segment.current_share / widest) * 100}%` }} />
                  </div>
                </td>
                <td className="num">{pct(segment.baseline_share, 0)}</td>
                <td className="num">{pct(segment.current_share, 0)}</td>
                <td className="num">{pct(segment.conversion_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ImpactLine impact={hypothesis.impact} currency={currency} />
    </article>
  );
}
