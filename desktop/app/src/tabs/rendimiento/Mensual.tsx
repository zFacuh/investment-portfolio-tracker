import type { Rendimiento } from "../../api";
import { Card } from "../../components/ui";
import { num } from "../../format";
import { t } from "../../i18n";
import { alfa, useTema } from "../../theme/tema";

/** Heatmap anio x mes del TWR mensual (verde sube, rojo baja; intensidad = magnitud). */
export function Mensual({ mensual, unidad }: { mensual: Rendimiento["mensual"]; unidad: string }) {
  const { colores: c } = useTema();
  if (!mensual) {
    return (
      <Card titulo="Rendimiento mes a mes">
        <div className="vacio">{t("Todavía no hay meses completos.")}</div>
      </Card>
    );
  }
  const todos = mensual.valores.flat().filter((v): v is number => v != null);
  const lim = Math.max(...todos.map(Math.abs), 1);
  const fondo = (v: number | null) => (v == null ? "transparent" : alfa(v >= 0 ? c.pos : c.neg, 0.12 + 0.6 * Math.min(Math.abs(v) / lim, 1)));
  const txt = (v: number | null) => (v == null ? "" : `${v > 0 ? "+" : ""}${num(v, 1)}%`);

  const celdas: { anio: number; mes: string; v: number }[] = [];
  mensual.anios.forEach((a, i) => mensual.meses.forEach((m, j) => mensual.valores[i][j] != null && celdas.push({ anio: a, mes: m, v: mensual.valores[i][j]! })));
  const positivos = celdas.filter((x) => x.v > 0).length;
  const mejor = celdas.reduce((a, b) => (b.v > a.v ? b : a), celdas[0]);
  const peor = celdas.reduce((a, b) => (b.v < a.v ? b : a), celdas[0]);

  return (
    <Card titulo="Rendimiento mes a mes" sub={t("TWR mensual en {u}", { u: unidad })}>
      <div className="heatmap" style={{ gridTemplateColumns: `52px repeat(${mensual.meses.length}, 1fr) 72px` }}>
        <span />
        {mensual.meses.map((m) => (
          <span key={m} className="hm-col">
            {t(m)}
          </span>
        ))}
        <span className="hm-col">{t("Año")}</span>
        {mensual.anios.map((a, i) => (
          <div key={a} style={{ display: "contents" }}>
            <span className="hm-anio">{a}</span>
            {mensual.valores[i].map((v, j) => (
              <span key={j} className="hm-celda" style={{ background: fondo(v) }} title={v == null ? undefined : `${t(mensual.meses[j])} ${a}: ${txt(v)}`}>
                {txt(v)}
              </span>
            ))}
            <span className={`hm-celda hm-total ${mensual.anual[i] == null ? "" : mensual.anual[i]! >= 0 ? "pos" : "neg"}`}>{txt(mensual.anual[i])}</span>
          </div>
        ))}
      </div>
      {celdas.length > 0 && (
        <div className="cfg-nota faint">
          {t("{p} de {n} meses positivos · mejor mes: {mm} {ma} ({mv}) · peor mes: {pm} {pa} ({pv}). El primer mes es parcial (desde tu primera operación).", { p: positivos, n: celdas.length, mm: t(mejor.mes), ma: mejor.anio, mv: txt(mejor.v), pm: t(peor.mes), pa: peor.anio, pv: txt(peor.v) })}
        </div>
      )}
    </Card>
  );
}
