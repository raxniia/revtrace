import { useEffect, useState } from "react";
import { api } from "./api";
import { Rail } from "./components/Rail";
import { useLoad, useRoute } from "./hooks";
import { ActionsPage } from "./pages/Actions";
import { DataPage } from "./pages/Data";
import { InvestigationPage } from "./pages/Investigation";
import { InvestigationsPage } from "./pages/Investigations";
import { OverviewPage } from "./pages/Overview";

export function App() {
  const route = useRoute();
  const config = useLoad(() => api.config(), []);
  const [dataset, setDataset] = useState("");
  const [pending, setPending] = useState(0);
  const active = dataset || config.data?.default_dataset || "";

  const refreshPending = () =>
    api
      .actions()
      .then(({ actions }) => setPending(actions.filter((a) => a.status === "pending").length))
      .catch(() => setPending(0));

  useEffect(() => {
    refreshPending();
  }, [route]);

  const detail = route.match(/^\/investigations\/([\w-]+)/);

  return (
    <div className="shell">
      <Rail route={route} config={config.data} dataset={active} pending={pending} onDataset={setDataset} />
      <main className="page">
        {config.error && <p className="notice error">The API is not reachable: {config.error}</p>}
        {active &&
          (detail ? (
            <InvestigationPage key={detail[1]} id={detail[1]} onDecided={refreshPending} />
          ) : route.startsWith("/investigations") ? (
            <InvestigationsPage dataset={active} />
          ) : route.startsWith("/actions") ? (
            <ActionsPage onDecided={refreshPending} />
          ) : route.startsWith("/data") ? (
            <DataPage
              dataset={active}
              onUploaded={(name) => {
                config.reload();
                setDataset(name);
              }}
            />
          ) : (
            <OverviewPage dataset={active} />
          ))}
      </main>
    </div>
  );
}
