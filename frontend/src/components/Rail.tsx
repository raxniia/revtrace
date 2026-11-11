import type { Config } from "../types";

const LINKS = [
  { path: "/", label: "Overview" },
  { path: "/investigations", label: "Investigations" },
  { path: "/actions", label: "Actions" },
  { path: "/data", label: "Data" },
];

interface Props {
  route: string;
  config: Config | null;
  dataset: string;
  pending: number;
  onDataset: (name: string) => void;
}

export function Rail({ route, config, dataset, pending, onDataset }: Props) {
  const active = (path: string) => (path === "/" ? route === "/" : route.startsWith(path));
  return (
    <aside className="rail">
      <a className="wordmark" href="#/">
        <svg viewBox="0 0 30 22" aria-hidden="true">
          <path
            d="M1 14h6l3-10 5 16 3-9h11"
            fill="none"
            stroke="#ffe45c"
            strokeWidth="2.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        RevTrace
      </a>
      <nav className="nav" aria-label="Main">
        {LINKS.map((link) => (
          <a key={link.path} href={`#${link.path}`} aria-current={active(link.path) ? "page" : undefined}>
            {link.label}
            {link.path === "/actions" && pending > 0 && <span className="badge">{pending}</span>}
          </a>
        ))}
      </nav>
      <div className="rail-foot">
        <label>
          Dataset
          <select value={dataset} onChange={(event) => onDataset(event.target.value)}>
            {(config?.datasets ?? [dataset]).map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <div className="engine">
          Investigations run on
          <br />
          <strong>{config ? (config.agentic ? config.model : "statistical baseline") : "…"}</strong>
        </div>
      </div>
    </aside>
  );
}
