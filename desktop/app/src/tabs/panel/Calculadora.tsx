import { useState } from "react";
import { postRebalanceo, type Panel, type Rebalanceo } from "../../api";
import { Orden } from "../../components/Orden";
import { Card, MiniKpi, MontoInput, MontosRapidos } from "../../components/ui";
import { ars, num } from "../../format";
import { t, tm } from "../../i18n";

const RAPIDOS = [50_000, 100_000, 250_000, 500_000];

export function Calculadora({ p, reb, onResultado }: { p: Panel; reb: Rebalanceo | null; onResultado: (r: Rebalanceo | null) => void }) {
  const [monto, setMonto] = useState(100_000);
  const [calculando, setCalculando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const calcular = async () => {
    if (monto <= 0) return;
    setCalculando(true);
    setError(null);
    try {
      onResultado(await postRebalanceo(monto));
    } catch (e) {
      onResultado(null);
      setError((e as Error).message);
    } finally {
      setCalculando(false);
    }
  };

  return (
    <Card titulo="Calculadora DCA" sub="Aporte nuevo, sin vender">
      <label className="campo">
        <span>{t("Monto a invertir este mes")}</span>
        <MontoInput valor={monto} onChange={setMonto} onEnter={calcular} />
      </label>
      <MontosRapidos montos={RAPIDOS} valor={monto} onChange={setMonto} />
      <button className="btn-primario" onClick={calcular} disabled={calculando || monto <= 0}>
        {calculando ? t("Calculando…") : t("Calcular rebalanceo")}
      </button>
      {error && <div className="alerta error">{tm(error)}</div>}

      {reb ? (
        <div className="resultado">
          <div className="mini-kpis">
            <MiniKpi etq="Invertir" val={ars(reb.monto)} />
            <MiniKpi etq="Asignado (neto)" val={ars(reb.asignado)} tooltip="Nominales × precio, sin comisión/IVA." />
            <MiniKpi etq={t("Comisión est. ({p}%)", { p: num(p.comision_pct, 1) })} val={ars(reb.comision)} />
            <MiniKpi etq="Costo total est." val={ars(reb.costo_total)} fuerte tooltip="Lo que realmente te va a debitar el broker." />
          </div>
          <div className="vuelto">{t("Vuelto sin asignar: {v}", { v: ars(reb.vuelto) })}</div>
          {reb.ordenes.length === 0 ? (
            <div className="vacio">{t("Con este monto no alcanza para comprar ni un nominal. Probá con un monto mayor.")}</div>
          ) : (
            <div className="ordenes">
              {reb.ordenes.map((o) => (
                <Orden key={o.Ticker as string} o={o} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="vacio">{t("Ingresá un monto y calculá para ver las órdenes sugeridas. Enter también funciona.")}</div>
      )}
    </Card>
  );
}
