import { useEffect, useMemo, useState } from "react";
import { getContribucion, type Contribucion as ContribucionT, type UnidadId } from "../../api";
import { barrasSigno } from "../../components/graficos";
import { Grafico } from "../../components/Grafico";
import { Card, Segmento, Tabla, type Columna } from "../../components/ui";
import { dinero, num } from "../../format";
import { t, tm } from "../../i18n";
import { useTema } from "../../theme/tema";

type Periodo = "inicio" | "anio" | "12m" | "3m";
const PERIODOS: { id: Periodo; nombre: string }[] = [
  { id: "inicio", nombre: "Desde el inicio" },
  { id: "anio", nombre: "Este año" },
  { id: "12m", nombre: "12 meses" },
  { id: "3m", nombre: "3 meses" },
];
const TOP = 12;

type Fila = ContribucionT["filas"][number];

export function Contribucion({ unidad, version }: { unidad: UnidadId; version: number }) {
  const { colores: c } = useTema();
  const [periodo, setPeriodo] = useState<Periodo>("inicio");
  const [datos, setDatos] = useState<ContribucionT | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    getContribucion(unidad, periodo)
      .then((d) => vivo && (setDatos(d), setError(null)))
      .catch((e) => vivo && setError((e as Error).message));
    return () => {
      vivo = false;
    };
  }, [unidad, periodo, version]);

  const grafico = useMemo(() => {
    if (!datos?.filas.length) return null;
    // Mismo recorte que Streamlit: los que mas sumaron, los que mas restaron y el resto agrupado.
    let items = datos.filas.map((f) => ({ nombre: t(f.ticker), valor: f.contribucion ?? 0 }));
    if (items.length > TOP) {
      const pos = items.filter((x) => x.valor >= 0).slice(0, TOP / 2 + 2);
      const neg = items.filter((x) => x.valor < 0).slice(-(TOP / 2 - 2));
      const resto = items.filter((x) => !pos.includes(x) && !neg.includes(x));
      items = [...pos, ...(resto.length ? [{ nombre: t("Resto ({n})", { n: resto.length }), valor: resto.reduce((s, x) => s + x.valor, 0) }] : []), ...neg];
    }
    return { opcion: barrasSigno(c, items, (v) => dinero(v, unidad, true)), alto: items.length * 30 + 20 };
  }, [datos, c, unidad]);

  const columnas: Columna<Fila>[] = [
    { id: "t", nombre: "Activo", render: (f) => <b>{t(f.ticker)}</b>, orden: (f) => f.ticker },
    { id: "e", nombre: "Estado", render: (f) => <span className="muted">{t(f.estado)}</span>, orden: (f) => f.estado },
    { id: "vi", nombre: "Valor inicial", render: (f) => dinero(f.valor_inicial, unidad), orden: (f) => f.valor_inicial, der: true },
    { id: "fl", nombre: "Flujo neto", render: (f) => dinero(f.flujo, unidad, true), orden: (f) => f.flujo, der: true },
    { id: "vf", nombre: "Valor final", render: (f) => dinero(f.valor_final, unidad), orden: (f) => f.valor_final, der: true },
    { id: "c", nombre: "Contribución", render: (f) => <span className={(f.contribucion ?? 0) >= 0 ? "pos" : "neg"}>{dinero(f.contribucion, unidad, true)}</span>, orden: (f) => f.contribucion, der: true },
    { id: "p", nombre: "% del resultado", render: (f) => (f.pct_resultado == null ? "—" : `${num(f.pct_resultado, 1)}%`), orden: (f) => f.pct_resultado, der: true },
  ];

  const ganadores = datos?.filas.filter((f) => (f.contribucion ?? 0) > 0).length ?? 0;

  return (
    <Card titulo="Qué activos explican el resultado" sub="Contribución de cada posición en la unidad elegida" acciones={<Segmento valor={periodo} onChange={setPeriodo} opciones={PERIODOS} />}>
      {error && <div className="alerta error">{tm(error)}</div>}
      {!datos && !error && <div className="vacio">{t("Calculando…")}</div>}
      {datos && grafico && (
        <>
          <Grafico alto={grafico.alto} opcion={grafico.opcion} />
          <div className="cfg-nota faint">
            {t("Resultado del período:")} <b className={(datos.total ?? 0) >= 0 ? "pos" : "neg"}>{dinero(datos.total, unidad, true)}</b>. {t("{g} de {n} posiciones sumaron. Incluye activos que ya vendiste (su resultado quedó realizado). Los dividendos en efectivo van en una fila aparte porque el CSV de Cocos no dice de qué activo vienen.", { g: ganadores, n: datos.filas.length })}
          </div>
          <details className="detalle">
            <summary>{t("Ver tabla completa")}</summary>
            <Tabla columnas={columnas} filas={datos.filas} clave={(f) => f.ticker} ordenInicial={{ id: "c", asc: false }} />
          </details>
        </>
      )}
      {datos && !grafico && <div className="vacio">{t("No hay movimientos en este período.")}</div>}
    </Card>
  );
}
