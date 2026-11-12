/**
 * Constructores de opciones de ECharts reutilizables. Toman los colores del
 * tema (useTema().colores), nunca colores fijos.
 */
import type { EChartsOption, LineSeriesOption } from "echarts";
import type { SerieT } from "../api";
import { alfa, tooltipBase, type ColoresGrafico } from "../theme/tema";

export interface Linea {
  nombre: string;
  serie: SerieT;
  color: string;
  tipo?: "solid" | "dashed" | "dotted";
  ancho?: number;
  area?: boolean;
  oculta?: boolean;
}

/** Grafico de lineas temporal (ej. base 100) con leyenda clickeable, zoom y linea de referencia opcional. */
export function lineasTiempo(
  c: ColoresGrafico,
  lineas: Linea[],
  opts: { referencia?: number; formato?: (v: number) => string; eje?: (v: number) => string; zoom?: boolean } = {},
): EChartsOption {
  const fmt = opts.formato ?? ((v: number) => v.toFixed(1));
  const series: LineSeriesOption[] = lineas.map((l, i) => ({
    name: l.nombre,
    type: "line",
    showSymbol: false,
    data: l.serie.fechas.map((f, j) => [f, l.serie.valores[j]]),
    lineStyle: { width: l.ancho ?? 1.5, type: l.tipo ?? "solid", color: l.color },
    itemStyle: { color: l.color },
    areaStyle: l.area
      ? { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: alfa(l.color, 0.22) }, { offset: 1, color: alfa(l.color, 0) }] } }
      : undefined,
    z: lineas.length - i,
    markLine:
      i === 0 && opts.referencia != null
        ? { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: c.border, type: "solid" }, data: [{ yAxis: opts.referencia }] }
        : undefined,
  }));
  return {
    animationDuration: 500,
    grid: { left: 56, right: 18, top: 44, bottom: opts.zoom === false ? 28 : 64 },
    legend: {
      top: 0,
      textStyle: { color: c.muted },
      inactiveColor: c.faint,
      icon: "roundRect",
      itemWidth: 14,
      itemHeight: 3,
      selected: Object.fromEntries(lineas.filter((l) => l.oculta).map((l) => [l.nombre, false])),
    },
    tooltip: { trigger: "axis", ...tooltipBase(c), valueFormatter: (v) => (v == null ? "—" : fmt(v as number)) },
    xAxis: { type: "time", axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.faint }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, axisLabel: { color: c.faint, formatter: opts.eje }, splitLine: { lineStyle: { color: c.grid } } },
    dataZoom:
      opts.zoom === false
        ? undefined
        : [
            { type: "inside" },
            {
              type: "slider",
              height: 20,
              bottom: 10,
              borderColor: c.border,
              fillerColor: alfa(c.accent, 0.12),
              textStyle: { color: c.faint },
              handleStyle: { color: c.surface2, borderColor: c.capital },
              moveHandleStyle: { color: c.border },
              dataBackground: { lineStyle: { color: c.border }, areaStyle: { color: c.surface2 } },
            },
          ],
    series,
  };
}

/** Barras horizontales con signo (verde positivo / rojo negativo) y etiqueta al costado. */
export function barrasSigno(c: ColoresGrafico, items: { nombre: string; valor: number }[], formato: (v: number) => string): EChartsOption {
  const datos = [...items].reverse();
  return {
    animationDuration: 400,
    grid: { left: 90, right: 90, top: 6, bottom: 6, containLabel: false },
    tooltip: { trigger: "item", ...tooltipBase(c), formatter: (p: unknown) => { const x = p as { name: string; value: number }; return `${x.name}: ${formato(x.value)}`; } },
    xAxis: { type: "value", axisLabel: { show: false }, splitLine: { lineStyle: { color: c.grid } } },
    yAxis: { type: "category", data: datos.map((d) => d.nombre), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: c.text, fontWeight: 550 } },
    series: [
      {
        type: "bar",
        barWidth: 14,
        data: datos.map((d) => ({
          value: d.valor,
          name: d.nombre,
          itemStyle: { color: d.valor >= 0 ? c.pos : c.neg, borderRadius: 3 },
          // negativas: la etiqueta va adentro de la barra, asi no pisa los nombres del eje
          label: d.valor >= 0 ? { position: "right" } : { position: "insideLeft", color: c.text },
        })),
        label: { show: true, position: "right", color: c.muted, fontSize: 11, formatter: (x: { value: unknown }) => formato(x.value as number) },
        markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: c.border }, data: [{ xAxis: 0 }] },
      },
    ],
  };
}
