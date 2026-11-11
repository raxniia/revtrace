import type { HealthComponent } from "../types";

const R = 86;
const ARC = Math.PI * R;

export function HealthDial({ score, components }: { score: number; components: HealthComponent[] }) {
  const tone = score >= 70 ? "#1d7a4b" : score >= 45 ? "#a86400" : "#c2302a";
  return (
    <div className="dial">
      <svg viewBox="0 0 220 128" role="img" aria-label={`Sales health ${score} out of 100`}>
        <path d={`M24 112 A${R} ${R} 0 0 1 196 112`} fill="none" stroke="#e4e7ed" strokeWidth="14" strokeLinecap="round" />
        <path
          d={`M24 112 A${R} ${R} 0 0 1 196 112`}
          fill="none"
          stroke={tone}
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={`${(score / 100) * ARC} ${ARC}`}
        />
        <text className="dial-score" x="110" y="104" textAnchor="middle">{score}</text>
        <text className="dial-of" x="110" y="124" textAnchor="middle">out of 100</text>
      </svg>
      <ul className="gauges">
        {components.map((part) => (
          <li key={part.key}>
            <div className="row">
              <span>{part.label}</span>
              <span>{part.score}</span>
            </div>
            <div className="bar">
              <i style={{ width: `${part.score}%` }} />
            </div>
            <small>{part.detail}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}
