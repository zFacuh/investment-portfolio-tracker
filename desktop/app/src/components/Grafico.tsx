import { useEffect, useRef } from "react";
import * as echarts from "echarts";

/** Envoltorio minimo de ECharts: crea el grafico una vez y lo actualiza al cambiar `opcion`. */
export function Grafico({ opcion, alto }: { opcion: echarts.EChartsOption; alto: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
    };
  }, []);

  useEffect(() => {
    // Tipografia del tema (--font-body) para todo el texto del grafico.
    const fuente = getComputedStyle(document.documentElement).getPropertyValue("--font-body").trim() || "sans-serif";
    chart.current?.setOption({ ...opcion, textStyle: { fontFamily: fuente, ...(opcion.textStyle as object) } }, { notMerge: true });
  }, [opcion]);

  return <div ref={ref} style={{ width: "100%", height: alto }} />;
}
