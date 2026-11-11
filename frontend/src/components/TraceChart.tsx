import { useMemo, useState } from "react";
import { monthName, pct, shortDate } from "../format";
import { useWidth } from "../hooks";
import type { Changepoint, SeriesPoint } from "../types";

interface Props {
  series: SeriesPoint[];
  changepoint: Changepoint | null;
  current: string;
  baseline: string;
}

const HEIGHT = 270;
const FLAG = 152;
const PAD = { top: 34, right: 16, bottom: 30, left: 44 };

export function TraceChart({ series, changepoint, current, baseline }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const points = useMemo(() => series.filter((p) => p.rate_7d != null), [series]);

  const inner = Math.max(width - PAD.left - PAD.right, 10);
  const top = Math.max(...points.map((p) => p.rate_7d!), 0.01);
  const ceiling = Math.ceil(top * 100 / 4) * 4 / 100;
  const x = (i: number) => PAD.left + (i / Math.max(series.length - 1, 1)) * inner;
  const y = (rate: number) => PAD.top + (1 - rate / ceiling) * (HEIGHT - PAD.top - PAD.bottom);
  const index = (date: string) => series.findIndex((p) => p.date === date);
  const path = points.map((p, n) => `${n ? "L" : "M"}${x(index(p.date)).toFixed(1)},${y(p.rate_7d!).toFixed(1)}`).join("");

  const band = (month: string) => {
    const inside = series.map((p, i) => (p.date.startsWith(month) ? i : -1)).filter((i) => i >= 0);
    return inside.length ? { from: x(inside[0]), to: x(inside[inside.length - 1]) } : null;
  };
  const bands = [
    { month: baseline, area: band(baseline), fill: "#e4e7ed" },
    { month: current, area: band(current), fill: "#dfe4fb" },
  ];
  const shift = changepoint ? index(changepoint.date) : -1;
  const flagX = x(shift) + FLAG > width - PAD.right ? x(shift) - FLAG + 1 : x(shift) - 1;
  const focus = hover != null ? series[hover] : null;

  return (
    <div
      className="chart"
      ref={ref}
      onMouseMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        const ratio = (event.clientX - box.left - PAD.left) / inner;
        setHover(Math.min(series.length - 1, Math.max(0, Math.round(ratio * (series.length - 1)))));
      }}
      onMouseLeave={() => setHover(null)}
    >
      {width > 0 && (
        <svg height={HEIGHT} role="img" aria-label="Seven-day conversion rate over time">
          {bands.map(
            ({ month, area, fill }) =>
              area && (
                <g key={month}>
                  <rect x={area.from} y={PAD.top} width={area.to - area.from} height={HEIGHT - PAD.top - PAD.bottom} fill={fill} opacity="0.55" />
                  <text x={area.from + 8} y={PAD.top + 17}>
                    {area.to - area.from > 130 ? monthName(month) : monthName(month).slice(0, 3)}
                  </text>
                </g>
              ),
          )}
          {[0, 0.25, 0.5, 0.75, 1].map((step) => (
            <g key={step}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(ceiling * step)} y2={y(ceiling * step)} stroke="#d3d7e0" strokeDasharray={step ? "2 4" : undefined} />
              <text x={PAD.left - 8} y={y(ceiling * step) + 4} textAnchor="end">{pct(ceiling * step, 0)}</text>
            </g>
          ))}
          <path d={path} fill="none" stroke="#2743d6" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />
          {shift >= 0 && (
            <g>
              <line x1={x(shift)} x2={x(shift)} y1={PAD.top - 14} y2={HEIGHT - PAD.bottom} stroke="#171a2b" strokeWidth="1.5" />
              <rect x={flagX} y={PAD.top - 30} width={FLAG} height="20" fill="#ffe45c" />
              <text className="flag" x={flagX + 8} y={PAD.top - 16}>Shift detected {shortDate(changepoint!.date)}</text>
            </g>
          )}
          {focus && focus.rate_7d != null && (
            <g>
              <line x1={x(hover!)} x2={x(hover!)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke="#747a92" strokeDasharray="3 3" />
              <circle cx={x(hover!)} cy={y(focus.rate_7d)} r="4.5" fill="#fbfbf8" stroke="#2743d6" strokeWidth="2.4" />
            </g>
          )}
          <text x={PAD.left} y={HEIGHT - 8}>{shortDate(series[0].date)}</text>
          <text x={width - PAD.right} y={HEIGHT - 8} textAnchor="end">{shortDate(series[series.length - 1].date)}</text>
        </svg>
      )}
      {focus && focus.rate_7d != null && (
        <div className="chart-tip" style={{ left: x(hover!) }}>
          {shortDate(focus.date)}: {pct(focus.rate_7d)} over 7 days, {focus.leads} leads that day
        </div>
      )}
    </div>
  );
}
