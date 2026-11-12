import type { Panel } from "../../api";
import { Kpi } from "../../components/ui";
import { ars, fecha, pct, usd } from "../../format";
import { t, tb } from "../../i18n";

export function Kpis({ p }: { p: Panel }) {
  const k = p.kpis;
  const v = k.variacion;
  const esHoy = v.fecha === new Date().toISOString().slice(0, 10);
  return (
    <section className="kpis">
      <Kpi etiqueta="Valor total (ARS)" valor={ars(k.valor_ars)} delta={k.pnl_pct} deltaTxt={t("{v} vs. capital", { v: pct(k.pnl_pct, 1, true) })} tooltip="Ganancia/pérdida acumulada vs. el capital inyectado (DCA)." />
      <Kpi etiqueta="Valor total (USD CCL)" valor={usd(k.valor_usd)} sub={`CCL ${ars(p.ccl, 2)}`} />
      <Kpi
        etiqueta={esHoy ? "Hoy" : "Última rueda"}
        valor={v.ars == null ? t("N/D") : `${v.ars >= 0 ? "+" : "−"}${ars(Math.abs(v.ars))}`}
        delta={v.pct}
        deltaTxt={pct(v.pct, 2, true)}
        tooltip={
          v.suben.length
            ? t("Suben: {a}\nBajan: {b}", { a: v.suben.map((s) => `${s.ticker} ${pct(s.pct, 1, true)}`).join(", "), b: v.bajan.map((s) => `${s.ticker} ${pct(s.pct, 1, true)}`).join(", ") })
            : undefined
        }
      />
      <Kpi
        etiqueta="Peor brecha vs. capital"
        valor={pct(k.brecha_pct, 1)}
        tono={k.brecha_pct != null && k.brecha_pct < 0 ? "neg" : undefined}
        sub={k.brecha_fecha ? t("el {fecha}", { fecha: fecha(k.brecha_fecha) }) : undefined}
        tooltip="Peor brecha entre el valor de mercado y el capital invertido. No es un drawdown pico-a-valle."
      />
    </section>
  );
}

export function BarraMeta({ meta }: { meta: NonNullable<Panel["meta"]> }) {
  return (
    <div className="meta-barra">
      <div className="meta-barra-txt">
        <span>
          {tb("**{p}** de tu meta · te faltan {falta}", { p: pct(meta.pct, 1), falta: usd(meta.falta) })}
        </span>
        <span className="muted">
          {t("Meta {m}", { m: usd(meta.usd) })}
          {meta.fecha ? ` · ${fecha(meta.fecha).slice(3)}` : ""}
        </span>
      </div>
      <div className="track">
        <div className="fill" style={{ width: `${Math.min(meta.pct, 100)}%` }} />
      </div>
    </div>
  );
}
