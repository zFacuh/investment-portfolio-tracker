import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { postBanda, type Banda as ResultadoBanda, type Fila, type Panel } from "../../api";
import { Grafico } from "../../components/Grafico";
import { Orden } from "../../components/Orden";
import { Avisos, Card, Categoria, MiniKpi, MontoInput, Tabla, Ticker, type Columna } from "../../components/ui";
import { ars, num, pct } from "../../format";
import { tooltipBase, useColoresTicker, useTema } from "../../theme/tema";
import { t, tb, tm } from "../../i18n";


/**
 * Rebalanceo por banda de tolerancia (con ventas). Se recalcula solo al mover
 * la banda o el monto: el calculo usa la tenencia que el backend ya tiene en memoria.
 */
export function Banda({ p }: { p: Panel }) {
  const { colores: c } = useTema();
  const colores = useColoresTicker(p.orden_tickers);
  const [banda, setBanda] = useState(p.banda_default);
  const [montoNuevo, setMontoNuevo] = useState(0);
  const [res, setRes] = useState<ResultadoBanda | null>(null);
  const [calculando, setCalculando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pedido = useRef(0);

  useEffect(() => {
    const id = ++pedido.current;
    setCalculando(true);
    const t = setTimeout(async () => {
      try {
        const r = await postBanda(banda, montoNuevo);
        if (id === pedido.current) {
          setRes(r);
          setError(null);
        }
      } catch (e) {
        if (id === pedido.current) setError((e as Error).message);
      } finally {
        if (id === pedido.current) setCalculando(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [banda, montoNuevo, p]);

  const grafico = useMemo<EChartsOption | null>(() => {
    if (!res?.desviaciones.length) return null;
    const filas = [...res.desviaciones].sort((a, b) => (a["Desviacion pp"] as number) - (b["Desviacion pp"] as number));
    const colorEstado = (e: unknown) => (e === "Sobreponderado" ? c.neg : e === "Subponderado" ? c.pos : c.capital);
    const max = Math.max(banda * 1.6, ...filas.map((f) => Math.abs(f["Desviacion pp"] as number))) * 1.1;
    return {
      animationDuration: 400,
      grid: { left: 64, right: 56, top: 8, bottom: 24 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        ...tooltipBase(c),
        formatter: (ps: unknown) => {
          const f = filas[(ps as { dataIndex: number }[])[0].dataIndex];
          return `<b>${f.Ticker}</b> · ${t(String(f.Estado))}<br/>${t("Actual {a} · Objetivo {o}", { a: pct(f["% Actual"] as number, 2), o: pct(f["% Objetivo"] as number, 2) })}<br/>${t("Desvío {d} pp", { d: num(f["Desviacion pp"] as number, 2) })}`;
        },
      },
      xAxis: {
        type: "value",
        min: -max,
        max,
        axisLabel: { color: c.faint, formatter: (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)} pp` },
        splitLine: { lineStyle: { color: c.grid } },
      },
      yAxis: {
        type: "category",
        data: filas.map((f) => f.Ticker as string),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: c.text, fontWeight: 550 },
      },
      series: [
        {
          type: "bar",
          barWidth: 12,
          data: filas.map((f) => ({
            value: f["Desviacion pp"] as number,
            itemStyle: { color: colorEstado(f.Estado), borderRadius: 3 },
          })),
          label: {
            show: true,
            position: "right",
            color: c.muted,
            fontSize: 11,
            formatter: (x: { value: unknown }) => `${(x.value as number) > 0 ? "+" : ""}${(x.value as number).toFixed(1)}`,
          },
          markArea: {
            silent: true,
            itemStyle: { color: c.surface2 },
            data: [[{ xAxis: -banda }, { xAxis: banda }]],
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: c.border, type: "dashed" },
            label: { show: false },
            data: [{ xAxis: -banda }, { xAxis: banda }],
          },
        },
      ],
    };
  }, [res, banda, c]);

  const columnas: Columna<Fila>[] = [
    { id: "t", nombre: "Activo", render: (f) => <Ticker t={f.Ticker as string} color={colores[f.Ticker as string]} />, orden: (f) => f.Ticker as string },
    { id: "c", nombre: "Categoría", render: (f) => <Categoria c={f.Categoria as string} /> },
    { id: "e", nombre: "Estado", render: (f) => <Estado e={f.Estado as string} />, orden: (f) => f.Estado as string },
    { id: "o", nombre: "% Obj.", render: (f) => pct(f["% Objetivo"] as number, 2), orden: (f) => f["% Objetivo"] as number, der: true },
    { id: "a", nombre: "% Actual", render: (f) => pct(f["% Actual"] as number, 2), orden: (f) => f["% Actual"] as number, der: true },
    { id: "d", nombre: "Desvío", render: (f) => `${num(f["Desviacion pp"] as number, 2)} pp`, orden: (f) => f["Desviacion pp"] as number, der: true },
    { id: "v", nombre: "Valor actual", render: (f) => ars(f["Valor Actual ARS"] as number), orden: (f) => f["Valor Actual ARS"] as number, der: true },
    { id: "m", nombre: "Meta", render: (f) => ars(f["Meta ARS"] as number), orden: (f) => f["Meta ARS"] as number, der: true },
  ];

  const fuera = res ? res.desviaciones.filter((f) => f.Estado !== "Dentro de banda").length : 0;
  // core/ devuelve tambien las filas con 0 nominales (fuera de banda pero sin plata para operar).
  const ventas = res?.ventas.filter((o) => ((o["Nominales a Vender"] as number) ?? 0) > 0) ?? [];
  const compras = res?.compras.filter((o) => ((o["Nominales a Comprar"] as number) ?? 0) > 0) ?? [];
  const sinFondos = res?.compras.filter((o) => !((o["Nominales a Comprar"] as number) > 0)) ?? [];

  return (
    <Card
      titulo="Rebalanceo por banda de tolerancia"
      sub={res ? t("{f} de {n} activos fuera de la banda de ±{b} pp", { f: fuera, n: res.desviaciones.length, b: num(banda, 1) }) : "Incluye ventas"}
      acciones={calculando ? <div className="spinner chico" /> : undefined}
    >
      <div className="alerta">
        {tb("A diferencia de la Calculadora DCA, esta sección sugiere **vender**. Vender puede tener impacto impositivo (Bienes Personales / Ganancias) que acá **no** se estima: solo se descuenta la comisión/IVA del broker. Revisá cada venta antes de ejecutarla.")}
      </div>

      <div className="banda-controles">
        <label className="campo">
          <span className="campo-etq">
            {t("Banda de tolerancia")} <b>±{num(banda, 1)} pp</b>
          </span>
          <input type="range" min={1} max={20} step={0.5} value={banda} onChange={(e) => setBanda(Number(e.target.value))} />
          <div className="rango-ext">
            <span>{t("1 pp · más operaciones")}</span>
            <span>{t("20 pp · menos operaciones")}</span>
          </div>
        </label>
        <label className="campo">
          <span>{t("Monto nuevo a sumar (opcional)")}</span>
          <MontoInput chico valor={montoNuevo} onChange={setMontoNuevo} />
          <span className="faint">{t("0 = redistribuir solo lo que ya tenés")}</span>
        </label>
      </div>

      {error && <div className="alerta error">{tm(error)}</div>}

      {res && (
        <>
          <Avisos avisos={res.advertencias} titulo={t("{n} aclaración(es) sobre este cálculo", { n: res.advertencias.length })} />

          <div className="banda-grid">
            <div>
              <h3>{t("Desvío vs. objetivo")}</h3>
              {grafico && <Grafico alto={Math.max(220, res.desviaciones.length * 26 + 40)} opcion={grafico} />}
              <div className="leyenda-banda">
                <span><i className="neg-bg" /> {t("Sobreponderado · vender")}</span>
                <span><i className="pos-bg" /> {t("Subponderado · comprar")}</span>
                <span><i className="muted-bg" /> {t("Dentro de banda · no se toca")}</span>
              </div>
            </div>
            <div>
              <h3>{t("Resumen de efectivo")}</h3>
              <div className="mini-kpis">
                <MiniKpi etq="Venta neta" val={ars(res.venta_neta)} tooltip={t("Bruto {b} − comisión est. {c}", { b: ars(res.venta_bruta), c: ars(res.comision_venta) })} />
                <MiniKpi etq="Efectivo disponible" val={ars(res.efectivo_disponible)} tooltip="Venta neta + monto nuevo" />
                <MiniKpi etq="Costo compra total" val={ars(res.costo_compra)} fuerte tooltip="Nominales × precio + comisión estimada" />
                <MiniKpi etq="Efectivo sobrante" val={ars(res.efectivo_sobrante)} tooltip="Lo que no se pudo asignar (redondeo de nominales o sin subponderados)" />
              </div>

              <h3>{t("Órdenes sugeridas")}</h3>
              {ventas.length === 0 && compras.length === 0 && sinFondos.length === 0 ? (
                <div className="vacio">{t("Todo está dentro de la banda: no hay nada que vender ni comprar.")}</div>
              ) : (
                <div className="ordenes">
                  {ventas.map((o) => (
                    <Orden key={`v-${o.Ticker}`} o={o} tipo="venta" marcar />
                  ))}
                  {compras.map((o) => (
                    <Orden key={`c-${o.Ticker}`} o={o} tipo="compra" marcar />
                  ))}
                  {ventas.length === 0 && <div className="vacio">{t("Nada sobreponderado fuera de la banda: no hay ventas.")}</div>}
                  {sinFondos.length > 0 && (
                    <div className="vacio">
                      {t(sinFondos.length > 1 ? "{tk} están subponderados, pero no hay efectivo para comprar: sumá un monto nuevo arriba." : "{tk} está subponderado, pero no hay efectivo para comprar: sumá un monto nuevo arriba.", { tk: sinFondos.map((o) => o.Ticker).join(", ") })}
                    </div>
                  )}
                  {compras.length === 0 && sinFondos.length === 0 && <div className="vacio">{t("Nada subponderado fuera de la banda: no hay compras.")}</div>}
                </div>
              )}
            </div>
          </div>

          <details className="detalle">
            <summary>{t("Ver tabla completa de desviaciones")}</summary>
            <Tabla columnas={columnas} filas={res.desviaciones} clave={(f) => f.Ticker as string} ordenInicial={{ id: "d", asc: false }} />
          </details>
        </>
      )}
    </Card>
  );
}

function Estado({ e }: { e: string }) {
  const clase = e === "Sobreponderado" ? "venta" : e === "Subponderado" ? "compra" : "muted";
  return <span className={`badge ${clase}`}>{t(e)}</span>;
}
