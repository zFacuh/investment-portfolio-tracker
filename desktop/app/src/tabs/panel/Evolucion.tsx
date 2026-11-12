import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import type { Curva } from "../../api";
import { Grafico } from "../../components/Grafico";
import { Card } from "../../components/ui";
import { ars } from "../../format";
import { t } from "../../i18n";
import { alfa, tooltipBase, useTema } from "../../theme/tema";

export function Evolucion({ curva }: { curva: Curva | null }) {
  const { colores: c } = useTema();
  const opcion = useMemo<EChartsOption | null>(() => {
    if (!curva) return null;
    const serie = (vals: (number | null)[]) => curva.fechas.map((f, i) => [f, vals[i]]);
    const bench = Object.entries(curva.benchmarks);
    return {
      animationDuration: 600,
      grid: { left: 70, right: 20, top: 40, bottom: 70 },
      legend: {
        top: 0,
        textStyle: { color: c.muted },
        inactiveColor: c.faint,
        icon: "roundRect",
        itemWidth: 14,
        itemHeight: 3,
        selected: Object.fromEntries(bench.map(([l]) => [t("Si hubieras comprado {x}", { x: l }), false])),
      },
      tooltip: { trigger: "axis", ...tooltipBase(c), valueFormatter: (v) => ars(v as number) },
      xAxis: { type: "time", axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.faint }, splitLine: { show: false } },
      yAxis: {
        type: "value",
        axisLabel: { color: c.faint, formatter: (v: number) => `$${(v / 1e6).toFixed(1)}M` },
        splitLine: { lineStyle: { color: c.grid } },
      },
      dataZoom: [
        { type: "inside" },
        {
          type: "slider",
          height: 22,
          bottom: 12,
          borderColor: c.border,
          fillerColor: alfa(c.accent, 0.12),
          textStyle: { color: c.faint },
          handleStyle: { color: c.surface2, borderColor: c.capital },
          moveHandleStyle: { color: c.border },
          dataBackground: { lineStyle: { color: c.border }, areaStyle: { color: c.surface2 } },
        },
      ],
      series: [
        {
          name: t("Valor de mercado"),
          type: "line",
          showSymbol: false,
          data: serie(curva.valor),
          lineStyle: { width: 2, color: c.valor },
          itemStyle: { color: c.valor },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: alfa(c.valor, 0.28) },
                { offset: 1, color: alfa(c.valor, 0) },
              ],
            },
          },
        },
        {
          name: t("Capital invertido"),
          type: "line",
          step: "end",
          showSymbol: false,
          data: serie(curva.capital),
          lineStyle: { width: 1.5, type: "dashed", color: c.capital },
          itemStyle: { color: c.capital },
        },
        ...bench.map(([label, vals], i) => ({
          name: t("Si hubieras comprado {x}", { x: label }),
          type: "line" as const,
          showSymbol: false,
          data: serie(vals),
          lineStyle: { width: 1.3, type: "dotted" as const, color: c.bench[i % c.bench.length] },
          itemStyle: { color: c.bench[i % c.bench.length] },
        })),
      ],
    };
  }, [curva, c]);

  return (
    <Card titulo="Evolución del portafolio" sub="Valor de mercado vs. capital invertido · rueda o arrastrá para hacer zoom · clic en la leyenda para sumar benchmarks">
      {opcion ? <Grafico alto={380} opcion={opcion} /> : <div className="vacio alto">{t("Reconstruyendo la curva histórica…")}</div>}
    </Card>
  );
}
