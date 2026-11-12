import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { getComposicion, getObjetivo, getRiesgoReal, getStress, type Barra } from "../../api";
import { lineasTiempo } from "../../components/graficos";
import { Grafico } from "../../components/Grafico";
import { Avisos, Card, MiniKpi } from "../../components/ui";
import { useDatos } from "../../components/useDatos";
import { dinero, fecha, fpct, num } from "../../format";
import { t, tb, tm } from "../../i18n";
import { alfa, tooltipBase, useTema } from "../../theme/tema";
import "./riesgo.css";

const AVISO_UNIVERSO =
  "Se mide sobre tu cartera de acciones y CEDEARs operada en Cocos (la misma que la curva del panel), incluidos los dividendos cobrados. No incluye cash sin invertir, FCI, cauciones ni bonos sin precio histórico.";

function Cargando({ texto }: { texto: string }) {
  return (
    <div className="carga-seccion">
      <div className="spinner chico" /> {t(texto)}
    </div>
  );
}

const n2 = (v: number | null | undefined) => (v == null ? t("N/D") : num(v, 2));
const pctSimple = (v: number | null | undefined, dec = 1) => (v == null ? t("N/D") : `${num(v, dec)}%`);

export function RiesgoTab({ version }: { version: number }) {
  return (
    <>
      <CarteraReal version={version} />
      <Stress version={version} />
      <Composicion version={version} />
      <CarteraObjetivo version={version} />
    </>
  );
}

// ------------------------------------------------------------------ C2 + C1
function CarteraReal({ version }: { version: number }) {
  const { colores: c } = useTema();
  const [rf, setRf] = useState<number | null>(null);
  const [rfDebounced, setRfDebounced] = useState<number | null>(null);
  useEffect(() => {
    const tm_ = setTimeout(() => setRfDebounced(rf), 300);
    return () => clearTimeout(tm_);
  }, [rf]);
  const { datos, error, cargando } = useDatos(() => getRiesgoReal(rfDebounced ?? undefined), [rfDebounced, version]);
  useEffect(() => {
    if (datos && rf == null) setRf(datos.rf);
  }, [datos, rf]);

  const volMovil = useMemo(() => {
    if (!datos || datos.metricas.error) return null;
    return lineasTiempo(
      c,
      [
        { nombre: t("Últimos 3 meses (63 ruedas)"), serie: datos.metricas.vol_3m, color: c.accent, ancho: 2 },
        { nombre: t("Último mes (21 ruedas)"), serie: datos.metricas.vol_1m, color: c.muted, ancho: 1.2 },
      ],
      { formato: (v) => `${num(v, 1)}%`, eje: (v) => `${v}%`, zoom: false },
    );
  }, [datos, c]);

  const dd = useMemo<EChartsOption | null>(() => {
    if (!datos) return null;
    const s = datos.drawdown.serie;
    return {
      animationDuration: 500,
      grid: { left: 56, right: 18, top: 12, bottom: 28 },
      tooltip: { trigger: "axis", ...tooltipBase(c), valueFormatter: (v) => `${num(v as number, 1)}%` },
      xAxis: { type: "time", axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.faint }, splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: { color: c.faint, formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: c.grid } } },
      series: [
        {
          name: t("Caída desde el máximo"),
          type: "line",
          showSymbol: false,
          data: s.fechas.map((f, i) => [f, s.valores[i]]),
          lineStyle: { width: 1.4, color: c.neg },
          itemStyle: { color: c.neg },
          areaStyle: { color: alfa(c.neg, 0.18) },
        },
      ],
    };
  }, [datos, c]);

  if (!datos) return <Card titulo="Riesgo y retorno de tu cartera real">{error ? <div className="alerta error">{tm(error)}</div> : <Cargando texto="Calculando métricas…" />}</Card>;
  const m = datos.metricas;
  const d = datos.drawdown;
  const moneda = datos.en_usd ? t("dólares") : t("pesos");

  return (
    <>
      <Card titulo="Riesgo y retorno de tu cartera real" sub={t("Medido en {m} · TWR", { m: moneda })} acciones={cargando ? <div className="spinner chico" /> : undefined}>
        <div className="rf">
          <label className="campo">
            <span>{t("Tasa libre de riesgo anual")}</span>
            <div className="input pct-rf">
              <input type="number" min={0} max={50} step={0.5} value={rf ?? ""} onChange={(e) => setRf(e.target.value === "" ? 0 : Number(e.target.value))} />
              <span>%</span>
            </div>
          </label>
          <span className="faint">{datos.en_usd ? t("En dólares, una letra del Tesoro de EE.UU. (~4%).") : t("En pesos, una tasa de plazo fijo o caución.")}</span>
        </div>
        {m.error ? (
          <div className="vacio">{tm(m.error)}</div>
        ) : (
          <>
            <div className="mini-kpis cinco">
              <MiniKpi etq="Volatilidad anual" val={pctSimple(m.volatilidad == null ? null : m.volatilidad * 100)} tooltip="Cuánto oscila tu cartera en un año típico (desvío estándar anualizado)." />
              <MiniKpi etq="Sharpe" val={n2(m.sharpe)} tooltip="Rendimiento extra sobre la tasa libre de riesgo por unidad de volatilidad. >1 es bueno, >2 muy bueno." />
              <MiniKpi etq="Sortino" val={n2(m.sortino)} tooltip="Como Sharpe, pero solo penaliza la volatilidad de las caídas." />
              <MiniKpi etq="Beta vs. S&P 500" val={n2(m.beta)} tooltip="Cuánto se mueve tu cartera cuando el S&P 500 se mueve 1%. 1 = igual que el mercado." />
              <MiniKpi etq="Correlación S&P" val={n2(m.correlacion)} tooltip="1 = se mueven igual; 0 = sin relación." />
            </div>
            <div className="cfg-nota faint">
              {t("Retorno anualizado del período: {r} · {n} ruedas analizadas. Beta y correlación contra SPY en la misma moneda.", { r: fpct(m.retorno_anual), n: m.ruedas })}
            </div>
            <h3>{t("Volatilidad móvil (anualizada)")}</h3>
            {volMovil && <Grafico alto={230} opcion={volMovil} />}
          </>
        )}
        <div className="cfg-nota faint">{t(AVISO_UNIVERSO)}</div>
      </Card>

      <Card titulo="Caídas desde el máximo" sub="Drawdown de tu cartera real, sobre el TWR (los aportes no lo tapan)">
        <div className="mini-kpis cuatro">
          <MiniKpi etq="Peor caída" val={pctSimple(d.max)} tooltip={t("Del {a} al {b}.", { a: fecha(d.fecha_pico), b: fecha(d.fecha_valle) })} />
          <MiniKpi etq="Duración de la caída" val={t("{n} días", { n: d.dias_caida })} tooltip={t("Del {a} al {b}.", { a: fecha(d.fecha_pico), b: fecha(d.fecha_valle) })} />
          <MiniKpi etq="Recuperación" val={d.dias_recuperacion != null ? t("{n} días", { n: d.dias_recuperacion }) : t("En curso")} tooltip={d.fecha_recuperacion ? t("Volvió al máximo el {f}.", { f: fecha(d.fecha_recuperacion) }) : "Todavía no volvió al máximo previo."} />
          <MiniKpi etq="Caída actual" val={pctSimple(d.actual)} tooltip="0% = hoy estás en máximos." />
        </div>
        {dd && <Grafico alto={250} opcion={dd} />}
        <div className="cfg-nota faint">{t("Cuánto estaba tu cartera por debajo de su máximo anterior, día a día. Es la medida de riesgo que más se siente: cuánto podés llegar a ver en rojo.")}</div>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ Stress test
function Stress({ version }: { version: number }) {
  const { colores: c } = useTema();
  const { datos, error } = useDatos(getStress, [version]);
  const [elegido, setElegido] = useState<string | null>(null);
  const esc = datos?.escenarios.find((e) => e.nombre === elegido) ?? datos?.escenarios[0];

  const detalle = useMemo<EChartsOption | null>(() => {
    if (!esc?.detalle.length) return null;
    const filas = [...esc.detalle].reverse();
    return {
      animationDuration: 400,
      grid: { left: 70, right: 70, top: 6, bottom: 22 },
      tooltip: {
        trigger: "item",
        ...tooltipBase(c),
        formatter: (p: unknown) => {
          const f = filas[(p as { dataIndex: number }).dataIndex];
          return `<b>${f.ticker}</b>: ${num(f.aporte, 1)} pp<br/>${t("cayó {r}% · pesa {p}%", { r: num(f.retorno, 0), p: num(f.peso, 1) })}<br/><span style="opacity:.7">${tm(f.fuente)}</span>`;
        },
      },
      xAxis: { type: "value", axisLabel: { color: c.faint, formatter: (v: number) => `${v} pp` }, splitLine: { lineStyle: { color: c.grid } } },
      yAxis: { type: "category", data: filas.map((f) => f.ticker), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: c.text, fontWeight: 550 } },
      series: [
        {
          type: "bar",
          barWidth: 12,
          data: filas.map((f) => ({ value: f.aporte, itemStyle: { color: (f.aporte ?? 0) < 0 ? c.neg : c.pos, borderRadius: 3 } })),
        },
      ],
    };
  }, [esc, c]);

  return (
    <Card titulo="Stress test" sub="Tu cartera de hoy (y la objetivo) en crisis pasadas, en dólares">
      {error && <div className="alerta error">{tm(error)}</div>}
      {!datos && !error && <Cargando texto="Descargando la historia de cada escenario (la primera vez tarda)…" />}
      {datos?.mensaje && <div className="vacio">{tm(datos.mensaje)}</div>}
      {datos && datos.escenarios.length > 0 && (
        <>
          <table className="tabla">
            <thead>
              <tr>
                <th>{t("Escenario")}</th>
                <th className="der">{t("Cartera de hoy")}</th>
                <th className="der">{t("Cartera objetivo")}</th>
                {datos.valor_usd != null && <th className="der">{t("Hoy, en US$")}</th>}
              </tr>
            </thead>
            <tbody>
              {datos.escenarios.map((e) => (
                <tr key={e.nombre} className={`clickeable ${e.nombre === esc?.nombre ? "fila-activa" : ""}`} onClick={() => setElegido(e.nombre)}>
                  <td>{t(e.nombre)}</td>
                  <td className={`der ${(e.hoy ?? 0) < 0 ? "neg" : "pos"}`}>
                    {fpct(e.hoy)}
                    {e.hoy_supuesto && " *"}
                  </td>
                  <td className={`der ${(e.objetivo ?? 0) < 0 ? "neg" : "pos"}`}>
                    {fpct(e.objetivo)}
                    {e.objetivo_supuesto && " *"}
                  </td>
                  {datos.valor_usd != null && <td className="der neg">{dinero(e.perdida_usd, "usd", true)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          {esc && (
            <>
              <h3>{t("Detalle por activo · {e} (clic en otra fila para cambiar)", { e: t(esc.nombre) })}</h3>
              {detalle && <Grafico alto={esc.detalle.length * 24 + 40} opcion={detalle} />}
            </>
          )}
          <div className="cfg-nota faint">
            {t("Aplica el movimiento real en dólares que tuvo cada activo (su subyacente en EE.UU., con dividendos) a tus pesos de hoy, sin aportes ni cambios en el medio. Los activos que no cotizaban en ese escenario usan el movimiento de QQQ como supuesto (* = más del 10% de la cartera con supuesto). IBIT usa la historia de bitcoin. En pesos la caída se vería distinta, porque en las crisis el CCL suele saltar.")}
          </div>
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ C3 + C4 + exposicion
function Barras({ titulo, items }: { titulo: string; items: Barra[] }) {
  const max = Math.max(...items.map((x) => x.pct ?? 0), 1);
  return (
    <div>
      <h3>{t(titulo)}</h3>
      <div className="barras-h">
        {items.map((x) => (
          <div key={x.nombre} className="barra-h" title={`${tm(x.nombre)}: ${pctSimple(x.pct)}`}>
            <span className="barra-h-nombre">{tm(x.nombre)}</span>
            <div className="barra-h-pista">
              <div style={{ width: `${((x.pct ?? 0) / max) * 100}%` }} />
            </div>
            <span className="barra-h-val">{num(x.pct, 0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Composicion({ version }: { version: number }) {
  const { colores: c } = useTema();
  const { datos, error } = useDatos(getComposicion, [version]);

  const riesgoGraf = useMemo<EChartsOption | null>(() => {
    const filas = datos?.riesgo.filas;
    if (!filas?.length) return null;
    const inv = [...filas].reverse();
    return {
      animationDuration: 400,
      grid: { left: 64, right: 24, top: 30, bottom: 24 },
      legend: { top: 0, textStyle: { color: c.muted }, icon: "roundRect", itemWidth: 12, itemHeight: 8 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipBase(c), valueFormatter: (v) => `${num(v as number, 1)}%` },
      xAxis: { type: "value", axisLabel: { color: c.faint, formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: c.grid } } },
      yAxis: { type: "category", data: inv.map((f) => f.ticker), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: c.text, fontWeight: 550 } },
      series: [
        { name: t("Peso en la cartera"), type: "bar", barGap: "15%", barWidth: 8, data: inv.map((f) => f.peso), itemStyle: { color: alfa(c.muted, 0.55), borderRadius: 2 } },
        { name: t("Aporte al riesgo"), type: "bar", barWidth: 8, data: inv.map((f) => f.riesgo), itemStyle: { color: c.accent, borderRadius: 2 } },
      ],
    };
  }, [datos, c]);

  if (!datos) {
    return (
      <Card titulo="Concentración">
        {error ? <div className="alerta error">{tm(error)}</div> : <Cargando texto="Consultando sector y país de cada activo (solo la primera vez)…" />}
      </Card>
    );
  }
  const k = datos.concentracion;
  const r = datos.riesgo;
  const top = r.filas?.[0];
  const mas = r.filas?.filter((f) => (f.ratio ?? 0) > 1.3).map((f) => f.ticker) ?? [];
  const x = datos.exposicion;

  return (
    <>
      <Card titulo="Concentración" sub="Tenencia actual completa">
        {k.error ? (
          <div className="vacio">{tm(k.error)}</div>
        ) : (
          <>
            <div className="mini-kpis cuatro">
              <MiniKpi etq={t("Mayor posición ({tk})", { tk: k.top1_ticker })} val={pctSimple(k.top1)} />
              <MiniKpi etq="Top 3" val={pctSimple(k.top3)} />
              <MiniKpi etq="Top 5" val={pctSimple(k.top5)} />
              <MiniKpi etq={t("Activos efectivos (de {n})", { n: k.n })} val={num(k.n_efectivo, 1)} tooltip="A cuántos activos de igual peso equivale tu diversificación real (1 / suma de pesos al cuadrado)." />
            </div>
            <div className="tres-col">
              <Barras titulo="Por sector" items={k.sector} />
              <Barras titulo="Por país" items={k.pais} />
              <Barras titulo="Por moneda" items={k.moneda} />
            </div>
            <div className="cfg-nota faint">
              {t('Los ETF se agrupan por su categoría (ej. Large Blend = S&P 500) porque no tienen un único sector. "Por moneda" es la exposición real: un CEDEAR cotiza en pesos pero sigue al dólar CCL. Sector y país salen de Yahoo Finance y se guardan 30 días en data/cache/.')}
            </div>
          </>
        )}
      </Card>

      <Card titulo="De dónde viene el riesgo" sub="Peso vs. contribución a la volatilidad · último año">
        {r.error ? (
          <div className="vacio">{tm(r.error)}</div>
        ) : (
          <>
            {riesgoGraf && <Grafico alto={r.filas.length * 28 + 60} opcion={riesgoGraf} />}
            {top && (
              <div className="cfg-nota">
                {tb("**{tk}** aporta el {r}% de la volatilidad con el {p}% del capital.", { tk: top.ticker, r: num(top.riesgo, 0), p: num(top.peso, 0) })}
                {mas.length > 0 && (
                  <>
                    {" "}
                    {tb("Aportan más riesgo que su peso: **{x}**.", { x: mas.join(", ") })}
                  </>
                )}{" "}
                <span className="faint">
                  {t("Se calcula con los rendimientos diarios en pesos del último año y tus pesos de hoy.")}
                  {r.sin_datos.length > 0 && ` ${t("Sin precio histórico (fuera del cálculo): {x}.", { x: r.sin_datos.join(", ") })}`}
                  {r.excluidos.length > 0 && ` ${t("Con menos de un mes de historia (fuera del cálculo): {x}.", { x: r.excluidos.join(", ") })}`}
                </span>
              </div>
            )}
          </>
        )}
      </Card>

      <Card titulo="Exposición real" sub="Lo que tenés directo + lo que tenés adentro de tus ETFs">
        {!x ? (
          <div className="vacio">{t("No hay posiciones valuadas.")}</div>
        ) : (
          <div className="expo-grid">
            <div>
              <h3>{t("Exposición total por empresa")}</h3>
              <table className="tabla">
                <thead>
                  <tr>
                    <th>{t("Empresa")}</th>
                    <th className="der">{t("Directo")}</th>
                    <th className="der">{t("Vía ETFs")}</th>
                    <th className="der">{t("Total")}</th>
                  </tr>
                </thead>
                <tbody>
                  {x.empresas.map((e) => (
                    <tr key={e.empresa} title={e.detalle}>
                      <td>
                        {e.empresa}
                        {x.superpuestas.includes(e.empresa) && <span className="badge otra superp">{t("superpuesta")}</span>}
                      </td>
                      <td className="der">{(e.directo ?? 0) > 0 ? pctSimple(e.directo) : <span className="faint">—</span>}</td>
                      <td className="der">{(e.via_etfs ?? 0) > 0 ? pctSimple(e.via_etfs) : <span className="faint">—</span>}</td>
                      <td className="der">
                        <b>{pctSimple(e.total)}</b>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {x.superpuestas.length > 0 && (
                <div className="cfg-nota">
                  {tb("**Superpuestas** (las tenés sueltas Y adentro de tus ETFs): {x}. Comprarlas sueltas es una apuesta extra a esas empresas, no diversificación.", { x: x.superpuestas.join(", ") })}
                </div>
              )}
            </div>
            <div>
              <h3>{t("Exposición a bitcoin")}</h3>
              {!x.btc ? (
                <div className="vacio">{t("No tenés activos ligados a bitcoin.")}</div>
              ) : (
                <>
                  <div className="mini-kpis">
                    <MiniKpi etq="Del capital" val={pctSimple(x.btc.capital)} />
                    <MiniKpi etq="Del riesgo" val={pctSimple(x.btc.riesgo)} fuerte tooltip="Cuánto de la volatilidad de tu cartera viene de estos activos (último año)." />
                  </div>
                  <ul className="lista-btc">
                    {x.btc.filas.map((f) => (
                      <li key={f.ticker}>
                        <b>{f.ticker}</b> <span className="muted">({pctSimple(f.peso)})</span>: {tm(f.que_es)}.
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        )}
        <div className="cfg-nota faint">{t("Fuente: mayores posiciones de cada ETF según Yahoo Finance (se guardan 30 días). Solo se publican las ~10 mayores, así que la exposición vía ETFs a empresas más chicas queda subestimada.")}</div>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ cartera objetivo
function CarteraObjetivo({ version }: { version: number }) {
  const { colores: c } = useTema();
  const { datos, error } = useDatos(getObjetivo, [version]);
  if (!datos) {
    return (
      <Card titulo="Tu cartera objetivo">
        {error ? <div className="alerta error">{tm(error)}</div> : <Cargando texto="Descargando el último año de precios de tus activos objetivo…" />}
      </Card>
    );
  }
  const tks = datos.correlacion.tickers;
  // Divergente: -1 = acento, 0 = superficie, +1 = rojo (mismo criterio que Streamlit)
  const fondo = (v: number | null) => (v == null ? "transparent" : alfa(v >= 0 ? c.neg : c.accent, 0.08 + 0.62 * Math.min(Math.abs(v), 1)));

  return (
    <Card titulo="Tu cartera objetivo" sub="Según los % de tu configuración · últimos 12 meses (no lo que ya tenés comprado)">
      <Avisos avisos={[...datos.advertencias, ...(datos.sin_datos.length ? [t("Sin histórico disponible para: {x} (quedan afuera).", { x: datos.sin_datos.join(", ") })] : [])]} titulo="Aclaraciones sobre estos datos" />
      <div className="mini-kpis" style={{ marginTop: 12 }}>
        <MiniKpi etq="Volatilidad anualizada del portafolio" val={pctSimple(datos.volatilidad)} />
        <MiniKpi etq="Max drawdown del portafolio (12m)" val={pctSimple(datos.max_drawdown)} tooltip="Caída pico-a-valle real. Distinta de la 'Peor brecha vs. capital' del Panel, que compara contra la plata que fuiste poniendo." />
      </div>
      <div className="expo-grid">
        <div>
          <h3>{t("Matriz de correlación")}</h3>
          <div className="corr" style={{ gridTemplateColumns: `56px repeat(${tks.length}, 1fr)` }}>
            <span />
            {tks.map((x) => (
              <span key={x} className="hm-col">
                {x}
              </span>
            ))}
            {tks.map((fila, i) => (
              <div key={fila} style={{ display: "contents" }}>
                <span className="hm-anio">{fila}</span>
                {datos.correlacion.valores[i].map((v, j) => (
                  <span key={j} className="hm-celda" style={{ background: fondo(v) }} title={`${fila} × ${tks[j]}: ${n2(v)}`}>
                    {v == null ? "" : num(v, 2)}
                  </span>
                ))}
              </div>
            ))}
          </div>
          <div className="cfg-nota faint">{t("Rendimientos diarios. Los CEDEARs cotizan en ARS: su correlación incluye el efecto del dólar CCL.")}</div>
        </div>
        <div>
          <h3>{t("Volatilidad y drawdown por activo")}</h3>
          <table className="tabla">
            <thead>
              <tr>
                <th>{t("Activo")}</th>
                <th className="der">{t("Volatilidad anual")}</th>
                <th className="der">{t("Max drawdown (12m)")}</th>
              </tr>
            </thead>
            <tbody>
              {datos.por_activo.map((a) => (
                <tr key={a.ticker}>
                  <td>
                    <b>{a.ticker}</b>
                  </td>
                  <td className="der">{pctSimple(a.volatilidad)}</td>
                  <td className="der neg">{pctSimple(a.max_drawdown)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="cfg-nota faint">{t("Ordenado de mayor a menor volatilidad.")}</div>
        </div>
      </div>
    </Card>
  );
}
