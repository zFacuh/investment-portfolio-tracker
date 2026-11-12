import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { getAportes, getCompras, type Aportes } from "../../api";
import { Grafico } from "../../components/Grafico";
import { Card, MiniKpi, Segmento } from "../../components/ui";
import { useDatos } from "../../components/useDatos";
import { dinero, num } from "../../format";
import { locale, t, tm } from "../../i18n";
import { alfa, tooltipBase, useTema, type ColoresGrafico } from "../../theme/tema";
import "./aportes.css";

/** "2025-07" -> "jul 25" (o "Jul 25" en ingles) */
const etiquetaMes = (ym: string) =>
  `${new Date(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)) - 1, 15).toLocaleDateString(locale(), { month: "short" }).replace(".", "")} ${ym.slice(2, 4)}`;

function Cargando({ texto }: { texto: string }) {
  return (
    <div className="carga-seccion">
      <div className="spinner chico" /> {t(texto)}
    </div>
  );
}

function ejesBarras(c: ColoresGrafico, meses: string[], formatoY: (v: number) => string, conY2: boolean): Partial<EChartsOption> {
  return {
    grid: { left: 64, right: conY2 ? 64 : 18, top: 36, bottom: 28 },
    xAxis: { type: "category", data: meses.map(etiquetaMes), axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.faint }, axisTick: { show: false } },
    yAxis: [
      { type: "value", axisLabel: { color: c.faint, formatter: formatoY }, splitLine: { lineStyle: { color: c.grid } } },
      ...(conY2 ? [{ type: "value" as const, axisLabel: { color: c.faint, formatter: formatoY }, splitLine: { show: false } }] : []),
    ],
    legend: { top: 0, textStyle: { color: c.muted }, icon: "roundRect", itemWidth: 12, itemHeight: 8 },
  };
}

const compacto = (pref: string) => (v: number) => {
  const a = Math.abs(v);
  // 1.500 -> "1.5k" (no "2k"): un decimal solo cuando hace falta, para no repetir etiquetas del eje.
  const s = a >= 1e6 ? `${num(a / 1e6, 1)}M` : a >= 1e3 ? `${num(a / 1e3, a % 1e3 ? 1 : 0)}k` : num(a, 0);
  return `${v < 0 ? "−" : ""}${pref}${s}`;
};

export function AportesTab({ version }: { version: number }) {
  const { datos, error } = useDatos(getAportes, [version]);
  if (!datos) return error ? <div className="alerta error">{tm(error)}</div> : <Card titulo="Tus aportes"><Cargando texto="Leyendo depósitos, retiros y dividendos…" /></Card>;
  return (
    <>
      <TusAportes a={datos.aportes} />
      <Dividendos d={datos.dividendos} />
      <TusCompras tickers={datos.tickers_operados} enUsd={datos.aportes.en_usd} version={version} />
    </>
  );
}

// ------------------------------------------------------------------ D1
function TusAportes({ a }: { a: Aportes["aportes"] }) {
  const { colores: c } = useTema();
  const [enUsd, setEnUsd] = useState(false);
  const opcion = useMemo<EChartsOption | null>(() => {
    if (a.error || !a.mensual.length) return null;
    const meses = a.mensual.map((m) => m.mes);
    const fmt = (v: unknown) => dinero(v as number, enUsd ? "usd" : "ars");
    if (enUsd) {
      return {
        animationDuration: 500,
        ...ejesBarras(c, meses, compacto("US$ "), true),
        tooltip: { trigger: "axis", ...tooltipBase(c), valueFormatter: fmt },
        series: [
          { name: t("Aporte neto"), type: "bar", barMaxWidth: 26, data: a.mensual.map((m) => ({ value: m.neto_usd, itemStyle: { color: (m.neto_usd ?? 0) >= 0 ? c.accent : c.neg, borderRadius: 3 } })) },
          { name: t("Acumulado"), type: "line", yAxisIndex: 1, data: a.mensual.map((m) => m.acumulado_usd), lineStyle: { color: c.muted, width: 1.6 }, itemStyle: { color: c.muted }, symbolSize: 5 },
        ],
      };
    }
    return {
      animationDuration: 500,
      ...ejesBarras(c, meses, compacto("$"), true),
      tooltip: { trigger: "axis", ...tooltipBase(c), valueFormatter: fmt },
      series: [
        { name: t("Depósitos"), type: "bar", stack: "f", barMaxWidth: 26, data: a.mensual.map((m) => m.depositos), itemStyle: { color: c.accent, borderRadius: [3, 3, 0, 0] } },
        { name: t("Retiros"), type: "bar", stack: "f", barMaxWidth: 26, data: a.mensual.map((m) => (m.retiros == null ? null : -Math.abs(m.retiros))), itemStyle: { color: alfa(c.neg, 0.75), borderRadius: [0, 0, 3, 3] } },
        { name: t("Aportado neto acumulado"), type: "line", yAxisIndex: 1, data: a.mensual.map((m) => m.acumulado), lineStyle: { color: c.muted, width: 1.6 }, itemStyle: { color: c.muted }, symbolSize: 5 },
      ],
    };
  }, [a, enUsd, c]);

  if (a.error) return <Card titulo="Tus aportes"><div className="vacio">{tm(a.error)}</div></Card>;
  return (
    <Card
      titulo="Tus aportes"
      sub="Depósitos y retiros de la cuenta"
      acciones={a.en_usd ? <Segmento valor={enUsd ? "usd" : "ars"} onChange={(v) => setEnUsd(v === "usd")} opciones={[{ id: "ars", nombre: "Pesos" }, { id: "usd", nombre: "Dólares" }]} /> : undefined}
    >
      <div className="mini-kpis cuatro">
        <MiniKpi etq="Aportado neto" val={dinero(a.neto, "ars")} tooltip={t("Depositado {d} menos retirado {r}.", { d: dinero(a.depositado, "ars"), r: dinero(a.retirado, "ars") })} />
        <MiniKpi etq="En dólares (CCL de cada día)" val={dinero(a.neto_usd, "usd")} fuerte />
        <MiniKpi etq="Promedio últimos 6 meses" val={dinero(a.promedio_6m, "ars")} tooltip={t("≈ {u} por mes. Sin contar el mes en curso.", { u: dinero(a.promedio_6m_usd, "usd") })} />
        <MiniKpi
          etq="Racha de aportes"
          val={`${a.racha} ${t(a.racha === 1 ? "mes" : "meses")}`}
          tooltip={t("Meses seguidos con al menos un depósito. {c} de {n} meses con aporte.", { c: a.meses_con_aporte, n: a.meses_totales })}
        />
      </div>
      {opcion && <Grafico alto={320} opcion={opcion} />}
      <div className="cfg-nota faint">
        {t("Es la plata que entró y salió de tu cuenta de Cocos (después se reparte entre acciones, FCI, caución, etc.). En dólares, cada depósito se convierte al CCL de su día. {c} de {n} meses con aporte.", { c: a.meses_con_aporte, n: a.meses_totales })}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ D3
function Dividendos({ d }: { d: Aportes["dividendos"] }) {
  const { colores: c } = useTema();
  const colorTipo = (tipo: string) => (tipo.includes("dolares") ? c.accent : tipo.includes("pesos") ? c.pos : tipo.includes("Cupones") ? c.warn : c.muted);
  const nombreTipo = (tipo: string) => t(tipo.replace("dolares", "dólares"));
  const opcion = useMemo<EChartsOption | null>(() => {
    if (d.error || !d.meses.length) return null;
    return {
      animationDuration: 500,
      ...ejesBarras(c, d.meses, compacto("$"), false),
      tooltip: { trigger: "axis", ...tooltipBase(c), valueFormatter: (v) => dinero(v as number, "ars") },
      series: Object.entries(d.por_tipo).map(([tipo, vals]) => ({
        name: nombreTipo(tipo),
        type: "bar" as const,
        stack: "div",
        barMaxWidth: 26,
        data: vals,
        itemStyle: { color: colorTipo(tipo) },
      })),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d, c]);

  if (d.error) return <Card titulo="Dividendos y rentas"><div className="vacio">{tm(d.error)}</div></Card>;
  return (
    <Card titulo="Dividendos y rentas" sub="Lo que te pagó tu cartera">
      <div className="mini-kpis tres">
        <MiniKpi etq="Cobrado (últimos 12 meses)" val={dinero(d.ultimos_12m_ars, "ars")} tooltip={`≈ ${dinero(d.ultimos_12m_usd, "usd", false, 2)}`} />
        <MiniKpi etq="Cobrado desde el inicio" val={dinero(d.total_ars, "ars")} tooltip={`≈ ${dinero(d.total_usd, "usd", false, 2)}`} />
        <MiniKpi etq="Rendimiento por dividendos" val={d.rendimiento == null ? t("N/D") : `${num(d.rendimiento * 100, 2)}%`} tooltip="Dividendos de los últimos 12 meses sobre el capital invertido hoy en acciones/CEDEARs." />
      </div>
      {opcion && <Grafico alto={270} opcion={opcion} />}
      <div className="cfg-nota faint">
        {t("Los dividendos de CEDEARs llegan en dólares (se valúan al CCL del día, netos de retenciones). El CSV de Cocos no indica de qué activo viene cada dividendo.")}
        {d.en_especie.length > 0 && ` ${t("También recibiste en especie: {x} (sin valuar: no tienen precio histórico).", { x: d.en_especie.map((x) => `${num(x.nominales, Number.isInteger(x.nominales) ? 0 : 2)} ${x.ticker}`).join(", ") })}`}
        {d.tiene_renta && ` ${t("Cupones y amortizaciones de bonos se muestran aparte: una amortización devuelve capital, no es ganancia.")}`}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ D4
function TusCompras({ tickers, enUsd, version }: { tickers: string[]; enUsd: boolean; version: number }) {
  const { colores: c } = useTema();
  const [ticker, setTicker] = useState(tickers[0] ?? "");
  const [unidad, setUnidad] = useState<"ars" | "usd">("ars");
  useEffect(() => {
    if (!tickers.includes(ticker) && tickers.length) setTicker(tickers[0]);
  }, [tickers, ticker]);
  const { datos, error, cargando } = useDatos(() => (ticker ? getCompras(ticker, unidad) : Promise.resolve(null)), [ticker, unidad, version]);

  const dec = unidad === "usd" ? 2 : 0;
  const opcion = useMemo<EChartsOption | null>(() => {
    if (!datos) return null;
    const maxQ = Math.max(...datos.operaciones.map((o) => o.cantidad ?? 0), 1);
    const tam = (q: number | null) => 8 + 14 * Math.sqrt((q ?? 0) / maxQ);
    const puntos = (tipo: string) => datos.operaciones.filter((o) => o.tipo === tipo).map((o) => ({ value: [o.fecha, o.precio], cantidad: o.cantidad, symbolSize: tam(o.cantidad) }));
    const fmt = (v: number) => dinero(v, unidad, false, 2);
    return {
      animationDuration: 500,
      grid: { left: 70, right: 24, top: 36, bottom: 28 },
      legend: { top: 0, textStyle: { color: c.muted }, itemWidth: 12, itemHeight: 8 },
      tooltip: {
        trigger: "item",
        ...tooltipBase(c),
        formatter: (p: unknown) => {
          const x = p as { seriesName: string; data: { value?: [string, number]; cantidad?: number } | [string, number] };
          if (Array.isArray(x.data)) return `${x.data[0]}: ${fmt(x.data[1])}`;
          return `${t(x.seriesName === t("Compras") ? "Compra de {n} a {p}" : "Venta de {n} a {p}", { n: num(x.data.cantidad, 0), p: fmt(x.data.value![1]) })}<br/><span style="opacity:.7">${x.data.value![0]}</span>`;
        },
      },
      xAxis: { type: "time", axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.faint }, splitLine: { show: false } },
      yAxis: { type: "value", scale: true, axisLabel: { color: c.faint, formatter: (v: number) => dinero(v, unidad, false, dec) }, splitLine: { lineStyle: { color: c.grid } } },
      series: [
        {
          name: t("Precio"),
          type: "line",
          showSymbol: false,
          data: datos.precio.fechas.map((f, i) => [f, datos.precio.valores[i]]),
          lineStyle: { color: c.muted, width: 1.6 },
          itemStyle: { color: c.muted },
          markLine: datos.timing
            ? {
                silent: true,
                symbol: "none",
                lineStyle: { color: c.accent, type: "dashed", width: 1.4 },
                label: { color: c.accent, formatter: t("Tu precio promedio de compra"), position: "insideStartTop", fontSize: 11 },
                data: [{ yAxis: datos.timing.promedio_compra ?? undefined }],
              }
            : undefined,
        },
        { name: t("Compras"), type: "scatter", symbol: "triangle", data: puntos("Compra"), itemStyle: { color: c.pos, borderColor: c.surface, borderWidth: 1 }, z: 5 },
        { name: t("Ventas"), type: "scatter", symbol: "triangle", symbolRotate: 180, data: puntos("Venta"), itemStyle: { color: c.neg, borderColor: c.surface, borderWidth: 1 }, z: 5 },
      ],
    };
  }, [datos, c, unidad, dec]);

  const tim = datos?.timing;
  return (
    <Card
      titulo="Tus compras sobre el gráfico"
      sub="¿Compraste barato o caro?"
      acciones={
        <div className="compras-ctrl">
          {cargando && <div className="spinner chico" />}
          <select className="input" value={ticker} onChange={(e) => setTicker(e.target.value)}>
            {tickers.map((tk) => (
              <option key={tk} value={tk}>
                {tk}
              </option>
            ))}
          </select>
          {enUsd && <Segmento valor={unidad} onChange={setUnidad} opciones={[{ id: "ars", nombre: "Pesos" }, { id: "usd", nombre: "Dólares" }]} />}
        </div>
      }
    >
      {!tickers.length && <div className="vacio">{t("No hay activos con operaciones y precio histórico.")}</div>}
      {error && <div className="alerta error">{tm(error)}</div>}
      {opcion && <Grafico alto={360} opcion={opcion} />}
      {tim && (
        <div className="mini-kpis cuatro">
          <MiniKpi etq="Tu precio promedio" val={dinero(tim.promedio_compra, unidad, false, dec)} tooltip="Promedio ponderado por nominales de todas tus compras." />
          <MiniKpi
            etq="DCA de referencia"
            val={dinero(tim.referencia_dca, unidad, false, dec)}
            tooltip={t("Precio promedio que habrías pagado invirtiendo un monto fijo todas las ruedas entre tu primera y tu última compra. Promedio simple del período: {p}.", { p: dinero(tim.promedio_periodo, unidad, false, dec) })}
          />
          <MiniKpi
            etq={(tim.ventaja_pct ?? 0) < 0 ? t("Timing vs. DCA · a tu favor") : t("Timing vs. DCA · en contra")}
            val={`${num(Math.abs(tim.ventaja_pct ?? 0), 1)}% ${(tim.ventaja_pct ?? 0) < 0 ? t("abajo") : t("arriba")}`}
            fuerte={(tim.ventaja_pct ?? 0) < 0}
            tooltip="Tu precio promedio contra el DCA mecánico. Abajo = tus decisiones de cuándo y cuánto comprar le ganaron a invertir lo mismo todos los días."
          />
          <MiniKpi etq="Compras bajo el precio actual" val={`${num(tim.bajo_precio_actual, 0)}%`} tooltip={t("{c} compras, {v} ventas.", { c: tim.n_compras, v: tim.n_ventas })} />
        </div>
      )}
      <div className="cfg-nota faint">
        {t("El tamaño de cada triángulo es proporcional a la cantidad operada. En dólares se saca el efecto del CCL: para un CEDEAR muestra si elegiste bien el momento del activo en sí.")}
      </div>
    </Card>
  );
}
