import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import type { Panel, Rebalanceo } from "../../api";
import { Grafico } from "../../components/Grafico";
import { Card, Segmento, Ticker } from "../../components/ui";
import { ars, pct } from "../../format";
import { parseColor } from "../../theme/diseno";
import { t } from "../../i18n";
import { tooltipBase, useColoresTicker, useTema, type ColoresGrafico } from "../../theme/tema";

/** Porcion minima (en % del total) para escribir el simbolo adentro; las mas finas quedan en el tooltip. */
const MIN_ETIQUETA = 4;

/** Texto oscuro sobre colores claros y blanco sobre oscuros, para que siempre se lea. */
function tintaSobre(color: string): string {
  const [r, g, b] = parseColor(color).map((x, i) => (i < 3 ? x / 255 : x));
  const lin = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L > 0.33 ? "rgba(10, 12, 18, 0.88)" : "rgba(255, 255, 255, 0.96)";
}

function dona(c: ColoresGrafico, datos: { name: string; value: number }[], colores: Record<string, string>, centro: string, enPct: boolean): EChartsOption {
  const total = datos.reduce((s, d) => s + d.value, 0) || 1;
  return {
    tooltip: { trigger: "item", ...tooltipBase(c), valueFormatter: (v) => (enPct ? pct(v as number, 1) : ars(v as number)) },
    title: { text: centro, left: "center", top: "center", textStyle: { color: c.muted, fontSize: 12.5, fontWeight: 600 } },
    series: [
      {
        type: "pie",
        // Anillo grueso: el simbolo y el % entran adentro de cada porcion.
        radius: ["44%", "94%"],
        center: ["50%", "50%"],
        itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 4 },
        label: {
          show: true,
          position: "inside",
          formatter: (x) => {
            const p = (Number(x.value) / total) * 100;
            return p >= MIN_ETIQUETA ? `{t|${x.name}}
{p|${pct(p, 1)}}` : "";
          },
        },
        labelLine: { show: false },
        emphasis: { scale: true, scaleSize: 5 },
        data: datos.map((d) => {
          const tinta = tintaSobre(colores[d.name] ?? c.accent);
          return {
            ...d,
            itemStyle: { color: colores[d.name] },
            label: {
              rich: {
                t: { color: tinta, fontSize: 11.5, fontWeight: 700, lineHeight: 15 },
                p: { color: tinta, fontSize: 10.5, fontWeight: 500, lineHeight: 13, opacity: 0.85 },
              },
            },
          };
        }),
        animationDuration: 500,
      },
    ],
  };
}

export function Distribucion({ p, reb }: { p: Panel; reb: Rebalanceo | null }) {
  const { colores: c } = useTema();
  const colores = useColoresTicker(p.orden_tickers);
  const [vista, setVista] = useState<"actual" | "proyectada">("actual");
  useEffect(() => setVista(reb ? "proyectada" : "actual"), [reb]);

  const actual = useMemo(
    () => p.tenencia.filter((f) => (f["Valor ARS"] as number) > 0).map((f) => ({ name: f.Ticker as string, value: f["Valor ARS"] as number })),
    [p.tenencia],
  );
  const proyectada = useMemo(() => {
    if (!reb) return null;
    const m = new Map(actual.map((d) => [d.name, d.value]));
    for (const [t, v] of Object.entries(reb.proyeccion)) m.set(t, (m.get(t) ?? 0) + (v ?? 0));
    return [...m].map(([name, value]) => ({ name, value }));
  }, [reb, actual]);
  const objetivo = p.objetivo.filter((o) => o.pct).map((o) => ({ name: o.ticker, value: o.pct as number }));

  const izq = vista === "proyectada" && proyectada ? proyectada : actual;
  const totalIzq = izq.reduce((s, d) => s + d.value, 0) || 1;
  const pesoIzq = new Map(izq.map((d) => [d.name, (d.value / totalIzq) * 100]));

  const filas = p.orden_tickers
    .map((t) => ({ t, real: pesoIzq.get(t) ?? 0, obj: p.objetivo.find((o) => o.ticker === t)?.pct ?? 0 }))
    .filter((f) => f.obj > 0 || f.real >= 0.5);
  const maxPeso = Math.max(...filas.map((f) => Math.max(f.real, f.obj)), 1);

  return (
    <Card
      titulo="Distribución vs. objetivo"
      sub="Por valor de mercado en ARS"
      acciones={
        <Segmento
          valor={vista}
          onChange={setVista}
          opciones={[
            { id: "actual", nombre: "Actual" },
            { id: "proyectada", nombre: "Proyectada", deshabilitado: !reb, tooltip: !reb ? "Calculá un rebalanceo primero" : undefined },
          ]}
        />
      }
    >
      <div className="donas">
        <Grafico alto={300} opcion={dona(c, izq, colores, vista === "actual" ? t("Actual") : t("Proyectada"), false)} />
        <Grafico alto={300} opcion={dona(c, objetivo, colores, t("Objetivo"), true)} />
      </div>
      <div className="desvios">
        <div className="desvio-head">
          <span>{t("Activo")}</span>
          <span>{vista === "actual" ? t("Peso actual vs. objetivo") : t("Peso proyectado vs. objetivo")}</span>
          <span className="der">{t("Desvío")}</span>
        </div>
        {filas.map((f) => {
          const d = f.real - f.obj;
          return (
            <div className="desvio" key={f.t}>
              <Ticker t={f.t} color={colores[f.t]} />
              <div className="barras">
                <div className="pista">
                  <div className="barra-real" style={{ width: `${(f.real / maxPeso) * 100}%`, background: colores[f.t] }} />
                  {f.obj > 0 && <div className="marca-obj" style={{ left: `${(f.obj / maxPeso) * 100}%` }} title={t("Objetivo {p}", { p: pct(f.obj, 1) })} />}
                </div>
                <span className="barra-txt">
                  {pct(f.real, 1)} <span className="faint">/ {f.obj > 0 ? pct(f.obj, 1) : "—"}</span>
                </span>
              </div>
              <span className={`der desvio-num ${Math.abs(d) >= 5 ? "warn" : ""}`}>{pct(d, 1, true)}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
