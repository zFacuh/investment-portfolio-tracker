import { useEffect, useState } from "react";
import type { Curva, Panel, Rebalanceo } from "../../api";
import { Avisos } from "../../components/ui";
import { Banda } from "./Banda";
import { Calculadora } from "./Calculadora";
import { Distribucion } from "./Distribucion";
import { Evolucion } from "./Evolucion";
import { BarraMeta, Kpis } from "./Kpis";
import { Tenencia } from "./Tenencia";
import "./panel.css";

export function PanelTab({ panel, curva }: { panel: Panel; curva: Curva | null }) {
  const [reb, setReb] = useState<Rebalanceo | null>(null);
  // Datos nuevos (refresco o config guardada): el rebalanceo anterior queda desactualizado.
  useEffect(() => setReb(null), [panel]);
  return (
    <>
      <Avisos avisos={panel.avisos} />
      <Kpis p={panel} />
      {panel.meta && <BarraMeta meta={panel.meta} />}
      <div className="grid-2">
        <Distribucion p={panel} reb={reb} />
        <Calculadora p={panel} reb={reb} onResultado={setReb} />
      </div>
      <Banda p={panel} />
      <Evolucion curva={curva} />
      <Tenencia p={panel} />
    </>
  );
}
