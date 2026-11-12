import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { getMetas, guardarMeta, guardarParametros, postProyeccion, type Metas, type ParamsProyeccion, type Proyeccion } from "../../api";
import { Grafico } from "../../components/Grafico";
import { Card, MiniKpi, MontoInput, Segmento } from "../../components/ui";
import { useDatos } from "../../components/useDatos";
import { dinero, fecha, fpct, num } from "../../format";
import { t, tb, tm } from "../../i18n";
import { alfa, tooltipBase, useTema } from "../../theme/tema";
import "./metas.css";

const usd = (v: number | null | undefined) => dinero(v, "usd");
const miles = (v: number | null | undefined) => (v == null ? t("N/D") : `US$ ${num(v / 1000, 0)}k`);

export function MetasTab({ version, recargar }: { version: number; recargar: () => void }) {
  const [vers, setVers] = useState(0);
  const { datos, error } = useDatos(getMetas, [version, vers]);
  if (!datos) return error ? <div className="alerta error">{tm(error)}</div> : <Card titulo="Tu meta patrimonial"><div className="carga-seccion"><div className="spinner chico" /> {t("Calculando tus valores de referencia…")}</div></Card>;
  if (datos.valor_usd == null) return <div className="alerta">{t("Hace falta el dólar CCL para medir la meta en dólares.")}</div>;
  return (
    <>
      <Meta m={datos} onGuardada={() => { setVers((v) => v + 1); recargar(); }} />
      <ProyeccionCard m={datos} />
    </>
  );
}

// ------------------------------------------------------------------ E1
function Meta({ m, onGuardada }: { m: Metas; onGuardada: () => void }) {
  const [meta, setMeta] = useState(m.meta_usd ?? 0);
  const [fechaObj, setFechaObj] = useState(m.fecha_objetivo ?? "");
  const [estado, setEstado] = useState<string | null>(null);
  const cambio = meta !== (m.meta_usd ?? 0) || fechaObj !== (m.fecha_objetivo ?? "");
  const hoy = new Date().toISOString().slice(0, 10);

  const guardar = async () => {
    try {
      await guardarMeta(meta || null, fechaObj || null);
      setEstado(t("Meta guardada."));
      onGuardada();
    } catch (e) {
      setEstado((e as Error).message);
    }
  };

  const pct = m.meta_usd ? (m.valor_usd! / m.meta_usd) * 100 : null;
  return (
    <Card titulo="Tu meta patrimonial" sub="En dólares de hoy (poder de compra actual)">
      <div className="meta-ctrl">
        <label className="campo">
          <span>{t("Meta")}</span>
          <MontoInput chico prefijo="US$" valor={meta} onChange={setMeta} onEnter={guardar} />
        </label>
        <label className="campo">
          <span>{t("Para cuándo (opcional)")}</span>
          <input className="input fecha" type="date" min={hoy} value={fechaObj} onChange={(e) => setFechaObj(e.target.value)} />
        </label>
        <button className="btn-secundario" onClick={guardar} disabled={!cambio}>
          {cambio ? t("Guardar meta") : t("Guardada")}
        </button>
      </div>
      {estado && <div className="cfg-nota faint">{estado}</div>}
      {pct != null ? (
        <div className="meta-barra" style={{ marginTop: 16 }}>
          <div className="meta-barra-txt">
            <span>
              {tb("Hoy: **{v}** ({p}%)", { v: usd(m.valor_usd), p: num(pct, 1) })}
            </span>
            <span className="muted">{t("Meta: {m}", { m: usd(m.meta_usd) })}</span>
          </div>
          <div className="track">
            <div className="fill" style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
          <div className="cfg-nota faint">
            {t("Te faltan {f}. Valor total de hoy convertido al CCL de hoy. La meta es en dólares de HOY: US$ 100.000 dentro de 20 años compran bastante menos que hoy, por eso la proyección de abajo usa rendimientos reales.", { f: usd(Math.max(m.meta_usd! - m.valor_usd!, 0)) })}
          </div>
        </div>
      ) : (
        <div className="cfg-nota faint">{t("Definí una meta para ver tu progreso acá y en el panel principal.")}</div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ E2
function ProyeccionCard({ m }: { m: Metas }) {
  const { colores: c } = useTema();
  const d = m.defaults;
  const inicial: ParamsProyeccion = {
    aporte: m.aporte_mensual_usd ?? Math.round(Math.max(d.aporte_real ?? 0, 0) / 10) * 10,
    escenario: m.escenario && m.escenario in m.escenarios ? m.escenario : "Moderado",
    volatilidad: Math.round((d.vol_real ?? 0.18) * 100) / 100,
    anios: m.horizonte_anios ?? 10,
  };
  const [p, setP] = useState<ParamsProyeccion>(inicial);
  const [res, setRes] = useState<Proyeccion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [estado, setEstado] = useState<string | null>(null);

  useEffect(() => {
    const espera = setTimeout(() => {
      postProyeccion(p)
        .then((r) => (setRes(r), setError(null)))
        .catch((e) => setError((e as Error).message));
    }, 250);
    return () => clearTimeout(espera);
  }, [p, m.meta_usd, m.fecha_objetivo]);

  const opcion = useMemo<EChartsOption | null>(() => {
    if (!res) return null;
    const f = res.fechas;
    const par = (a: (number | null)[]) => f.map((x, i) => [x, a[i]]);
    const dif = (a: (number | null)[], b: (number | null)[]) => f.map((x, i) => [x, a[i] != null && b[i] != null ? a[i]! - b[i]! : null]);
    const banda = { type: "line" as const, showSymbol: false, lineStyle: { width: 0 }, silent: true };
    return {
      animationDuration: 500,
      grid: { left: 76, right: 18, top: 40, bottom: 28 },
      legend: {
        top: 0,
        textStyle: { color: c.muted },
        itemWidth: 14,
        itemHeight: 8,
        data: [
          { name: t("Escenario central"), icon: "roundRect" },
          { name: t("80% de los escenarios"), icon: "rect", itemStyle: { color: alfa(c.accent, 0.25) } },
          { name: t("50% de los escenarios"), icon: "rect", itemStyle: { color: alfa(c.accent, 0.45) } },
          { name: t("Solo lo que aportás"), icon: "roundRect" },
        ],
      },
      tooltip: {
        trigger: "axis",
        ...tooltipBase(c),
        formatter: (ps: unknown) => {
          const i = (ps as { dataIndex: number }[])[0].dataIndex;
          return `<b>${f[i].slice(0, 7)}</b><br/>${t("Optimista (p90)")}: ${usd(res.p90[i])}<br/>${t("Central")}: <b>${usd(res.p50[i])}</b><br/>${t("Pesimista (p10)")}: ${usd(res.p10[i])}<br/><span style="opacity:.7">${t("Aportado")}: ${usd(res.aportado.valores[i])}</span>`;
        },
      },
      xAxis: { type: "time", axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.faint }, splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: { color: c.faint, formatter: (v: number) => miles(v) }, splitLine: { lineStyle: { color: c.grid } } },
      series: [
        // Bandas: base invisible (p10 / p25) + ancho apilado encima
        { ...banda, name: "_b80", stack: "b80", data: par(res.p10) },
        { ...banda, name: t("80% de los escenarios"), stack: "b80", data: dif(res.p90, res.p10), areaStyle: { color: alfa(c.accent, 0.12) }, itemStyle: { color: alfa(c.accent, 0.3) } },
        { ...banda, name: "_b50", stack: "b50", data: par(res.p25) },
        { ...banda, name: t("50% de los escenarios"), stack: "b50", data: dif(res.p75, res.p25), areaStyle: { color: alfa(c.accent, 0.22) }, itemStyle: { color: alfa(c.accent, 0.5) } },
        {
          name: t("Escenario central"),
          type: "line",
          showSymbol: false,
          data: par(res.p50),
          lineStyle: { color: c.accent, width: 2.4 },
          itemStyle: { color: c.accent },
          markLine: m.meta_usd
            ? { silent: true, symbol: "none", lineStyle: { color: c.warn, type: "dotted", width: 1.4 }, label: { color: c.warn, formatter: t("Meta {m}", { m: usd(m.meta_usd) }), position: "insideStartTop" }, data: [{ yAxis: m.meta_usd }] }
            : undefined,
        },
        { name: t("Solo lo que aportás"), type: "line", showSymbol: false, data: res.aportado.fechas.map((x, i) => [x, res.aportado.valores[i]]), lineStyle: { color: c.muted, width: 1.4, type: "dashed" }, itemStyle: { color: c.muted } },
      ],
    };
  }, [res, c, m.meta_usd]);

  const guardar = async () => {
    try {
      await guardarParametros(p);
      setEstado(t("Parámetros guardados."));
    } catch (e) {
      setEstado((e as Error).message);
    }
  };

  return (
    <Card titulo="Proyección" sub="Simulación de 2.000 escenarios posibles · se recalcula al cambiar cualquier parámetro">
      <div className="proy-ctrl">
        <label className="campo">
          <span>{t("Aporte mensual")}</span>
          <MontoInput chico prefijo="US$" valor={p.aporte} onChange={(v) => setP({ ...p, aporte: v })} />
          <span className="faint">{d.aporte_real != null ? t("Tu promedio real de 6 meses: {u}", { u: usd(d.aporte_real) }) : " "}</span>
        </label>
        <label className="campo">
          <span>{t("Escenario (rendimiento anual real en USD)")}</span>
          <Segmento valor={p.escenario} onChange={(v) => setP({ ...p, escenario: v })} opciones={Object.entries(m.escenarios).map(([k, v]) => ({ id: k, nombre: `${t(k)} ${num(v * 100, 0)}%` }))} />
          <span className="faint">{d.twr_real != null ? t("Tu TWR anual en USD hasta hoy: {r} (nominal, período corto)", { r: fpct(d.twr_real) }) : t("S&P 500 histórico: ~7% real")}</span>
        </label>
        <label className="campo">
          <span className="campo-etq">
            {t("Volatilidad anual")} <b>{num(p.volatilidad * 100, 0)}%</b>
          </span>
          <input type="range" min={0} max={0.8} step={0.01} value={p.volatilidad} onChange={(e) => setP({ ...p, volatilidad: Number(e.target.value) })} />
          <span className="faint">
            {t("Tu cartera, últimos 12 meses: {v}", { v: d.vol_real != null ? `${num(d.vol_real * 100, 0)}%` : t("N/D") })}
            {d.vol_hist != null && ` · ${t("todo el historial: {v}", { v: `${num(d.vol_hist * 100, 0)}%` })}`}
          </span>
        </label>
        <label className="campo">
          <span className="campo-etq">
            {t("Horizonte")} <b>{t("{n} años", { n: p.anios })}</b>
          </span>
          <input type="range" min={1} max={40} step={1} value={p.anios} onChange={(e) => setP({ ...p, anios: Number(e.target.value) })} />
          <div className="rango-ext">
            <span>1</span>
            <span>{t("{n} años", { n: 40 })}</span>
          </div>
        </label>
      </div>

      {error && <div className="alerta error">{tm(error)}</div>}
      {opcion && <Grafico alto={380} opcion={opcion} />}
      {res && (
        <div className="mini-kpis tres">
          <MiniKpi etq={t("En {n} años (escenario central)", { n: p.anios })} val={usd(res.final_p50)} fuerte tooltip={t("Aportando {a} en total.", { a: usd(res.aportado_extra) })} />
          <MiniKpi etq="Rango probable (80%)" val={`${miles(res.final_p10)} – ${miles(res.final_p90)}`} />
          {m.meta_usd ? (
            res.mes_meta ? (
              <MiniKpi etq={t("Llegás a la meta (central) · {p}% de prob. en {n} años", { p: num((res.prob_meta ?? 0) * 100, 0), n: p.anios })} val={`${res.mes_meta.slice(5)}/${res.mes_meta.slice(0, 4)}`} />
            ) : (
              <MiniKpi etq={t("Probabilidad de llegar a la meta en {n} años", { n: p.anios })} val={`${num((res.prob_meta ?? 0) * 100, 0)}%`} />
            )
          ) : (
            <MiniKpi etq="Meta" val={t("Sin definir")} />
          )}
        </div>
      )}
      {res?.prob_meta_en_fecha != null && m.fecha_objetivo && (
        <div className="cfg-nota">
          {tb("Probabilidad de llegar a la meta para el {f}: **{p}%**.", { f: fecha(m.fecha_objetivo), p: num(res.prob_meta_en_fecha * 100, 0) })}
        </div>
      )}
      <div className="proy-pie">
        <button className="btn-secundario chico" onClick={guardar}>
          {t("Recordar estos parámetros")}
        </button>
        {estado && <span className="faint">{estado}</span>}
      </div>
      <div className="cfg-nota faint">
        {t("Es una simulación, no una predicción: cada escenario sortea rendimientos mensuales con el rendimiento y la volatilidad elegidos (en dólares, sin impuestos ni comisiones). Todos los montos están en dólares de HOY: el rendimiento es real y el aporte se supone constante en poder de compra, o sea que en la práctica tu aporte en dólares nominales tiene que ir subiendo con la inflación para que esta proyección se cumpla.")}
      </div>
    </Card>
  );
}
