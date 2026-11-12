import { useEffect, useMemo, useState } from "react";
import { getRendimiento, type Rendimiento, type UnidadId } from "../../api";
import { lineasTiempo, type Linea } from "../../components/graficos";
import { Grafico } from "../../components/Grafico";
import { Avisos, Cargando, Card, Kpi, Segmento } from "../../components/ui";
import { dinero, fecha, fpct, num, pp } from "../../format";
import { t, tm } from "../../i18n";
import { useTema } from "../../theme/tema";
import { Contribucion } from "./Contribucion";
import { Mensual } from "./Mensual";
import { TirCuenta } from "./TirCuenta";
import "./rendimiento.css";

/** "Dolares (CCL)" -> "Dólares (CCL)" para mostrar. */
const nombreUnidad = (n: string) => t(n === "Dolares (CCL)" ? "Dólares (CCL)" : n);

const AVISO_UNIVERSO =
  "Se mide sobre tu cartera de acciones y CEDEARs operada en Cocos (la misma que la curva del panel), incluidos los dividendos cobrados. No incluye cash sin invertir, FCI, cauciones ni bonos sin precio histórico.";

export function RendimientoTab({ version }: { version: number }) {
  const { colores: c } = useTema();
  const [unidad, setUnidad] = useState<UnidadId>("usd");
  const [datos, setDatos] = useState<Rendimiento | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vivo = true;
    setCargando(true);
    getRendimiento(unidad)
      .then((d) => vivo && (setDatos(d), setError(null)))
      .catch((e) => vivo && setError((e as Error).message))
      .finally(() => vivo && setCargando(false));
    return () => {
      vivo = false;
    };
  }, [unidad, version]);

  const acumulado = useMemo(() => {
    if (!datos) return null;
    const lineas: Linea[] = [
      { nombre: t("Tu cartera"), serie: datos.acumulado.cartera, color: c.valor, ancho: 2.4, area: true },
      ...Object.entries(datos.acumulado.benchmarks).map(([l, s], i) => ({ nombre: l, serie: s, color: c.bench[i % c.bench.length], tipo: "dotted" as const, ancho: 1.4 })),
      ...Object.entries(datos.acumulado.referencias).map(([l, s], i) => ({ nombre: t(l), serie: s, color: i === 0 ? c.warn : c.muted, tipo: "dashed" as const, ancho: 1.6 })),
    ];
    return lineasTiempo(c, lineas, { referencia: 100 });
  }, [datos, c]);

  const exceso = useMemo(() => {
    const series = datos?.vs_indice.filter((v) => v.serie_6m) ?? [];
    if (!series.length) return null;
    return lineasTiempo(
      c,
      series.map((v, i) => ({ nombre: `vs. ${v.label}`, serie: v.serie_6m!, color: c.bench[i % c.bench.length], ancho: 1.8 })),
      { referencia: 0, formato: (v) => `${v > 0 ? "+" : ""}${num(v, 1)} pp`, eje: (v) => `${v} pp`, zoom: false },
    );
  }, [datos, c]);

  const categorias = useMemo(() => {
    if (!datos?.categorias.length) return null;
    return lineasTiempo(
      c,
      datos.categorias.map((x, i) => ({ nombre: t(x.nombre), serie: x.serie, color: c.paleta[i % c.paleta.length], ancho: x.otros ? 1.5 : 2.2, tipo: x.otros ? ("dotted" as const) : ("solid" as const) })),
      { referencia: 100, zoom: false },
    );
  }, [datos, c]);

  if (!datos) return error ? <div className="alerta error">{tm(error)}</div> : <Cargando texto="Calculando rendimiento (TWR, TIR, benchmarks)…" sub="La primera vez descarga el dólar CCL histórico y la inflación." />;

  const r = datos.resumen;
  const u = datos.unidad;
  const signo = (v: number | null | undefined) => (v == null ? "" : v >= 0 ? "pos" : "neg");

  return (
    <>
      <div className="rend-barra">
        <div>
          <Segmento valor={unidad} onChange={setUnidad} opciones={datos.unidades.map((x) => ({ id: x.id, nombre: nombreUnidad(x.nombre) }))} />
          <span className="faint rend-nota">{tm(datos.nota_unidad)}</span>
        </div>
        {cargando && <div className="spinner chico" />}
      </div>
      <Avisos avisos={datos.avisos} titulo={t("{n} aclaración(es) sobre los datos", { n: datos.avisos.length })} />

      <section className="kpis">
        <Kpi etiqueta="Ganancia acumulada" valor={dinero(r.ganancia, u, true)} delta={r.ganancia_pct} deltaTxt={fpct(r.ganancia_pct)} tooltip="Valor de hoy menos todo lo que pusiste (neto de ventas), en la unidad elegida." />
        <Kpi etiqueta="Rendimiento (TWR)" valor={fpct(r.twr_total)} tono={r.twr_total != null && r.twr_total < 0 ? "neg" : undefined} tooltip="Rendimiento ponderado por tiempo: mide tus decisiones sin el efecto de cuándo o cuánto aportaste. Es el que se compara contra un índice." />
        <Kpi etiqueta="TWR anualizado" valor={fpct(r.twr_anual)} sub={r.extrapolacion ? "período < 1 año: extrapolado" : "CAGR de tu estrategia"} tooltip="Llevado a tasa anual." />
        <Kpi etiqueta="TIR anual (acciones)" valor={fpct(r.tir_anual)} sub="incluye cuándo compraste" tooltip="XIRR de la plata puesta en acciones y CEDEARs. No incluye FCI, caución, cash ni bonos." />
      </section>
      <div className="faint rend-desde">{t("Desde el {f} ({d} días).", { f: fecha(r.fecha_inicio), d: r.dias })}</div>

      <Card titulo="El mismo resultado en las tres unidades" sub="En Argentina un rendimiento en pesos puede ser una pérdida real">
        <table className="tabla">
          <thead>
            <tr>
              <th>{t("Medido en")}</th>
              <th className="der">{t("Ganancia")}</th>
              <th className="der">TWR</th>
              <th className="der">{t("TWR anual")}</th>
              <th className="der">{t("TIR anual")}</th>
            </tr>
          </thead>
          <tbody>
            {datos.resumenes.map((x) => (
              <tr key={x.unidad} className={x.unidad === u ? "fila-activa" : ""} onClick={() => setUnidad(x.unidad)}>
                <td>{nombreUnidad(x.nombre)}</td>
                <td className={`der ${signo(x.ganancia)}`}>{dinero(x.ganancia, x.unidad, true)}</td>
                <td className={`der ${signo(x.twr_total)}`}>{fpct(x.twr_total)}</td>
                <td className={`der ${signo(x.twr_anual)}`}>{fpct(x.twr_anual)}</td>
                <td className={`der ${signo(x.tir_anual)}`}>{fpct(x.tir_anual)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card titulo="Rendimiento acumulado vs. referencias" sub="Base 100 al inicio · TWR · clic en la leyenda para mostrar u ocultar">
        {acumulado && <Grafico alto={380} opcion={acumulado} />}
        <div className="cfg-nota faint">
          {t("Cada benchmark simula tus mismos aportes, en las mismas fechas, puestos en ese índice (con dividendos), medido con TWR igual que tu cartera.")}
          {u === "ars" && ` ${t("En pesos se suman la inflación y el dólar CCL: si tu línea queda arriba, le ganaste.")}`} {t(AVISO_UNIVERSO)}
        </div>
      </Card>

      <Card titulo="¿Le ganás al índice?" sub={t("Tu cartera vs. tus mismos aportes puestos en cada índice, en {u}", { u: nombreUnidad(datos.unidades.find((x) => x.id === u)?.nombre ?? "") })}>
        {datos.vs_indice.length === 0 ? (
          <div className="vacio">{t("No hay benchmarks configurados con datos.")}</div>
        ) : (
          <>
            <table className="tabla">
              <thead>
                <tr>
                  <th />
                  <th className="der">{t("Últimos 6 meses")}</th>
                  <th className="der">{t("Últimos 12 meses")}</th>
                  <th className="der">{t("Desde el inicio")}</th>
                  <th className="der">{t("Ventanas de 6m ganadas")}</th>
                </tr>
              </thead>
              <tbody>
                {datos.vs_indice.map((v) => (
                  <tr key={v.label}>
                    <td>vs. {v.label}</td>
                    {[v.exceso_6m, v.exceso_12m, v.exceso_total].map((x, i) => (
                      <td key={i} className={`der ${x == null ? "faint" : signo(x)}`}>
                        {x == null ? t("Sin historia") : pp(x)}
                      </td>
                    ))}
                    <td className={`der ${v.pct_ventanas == null ? "faint" : v.pct_ventanas >= 50 ? "pos" : "neg"}`}>
                      {v.pct_ventanas == null ? t("Sin historia") : `${num(v.pct_ventanas, 0)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {exceso && (
              <>
                <h3>{t("Diferencia en ventanas móviles de 6 meses")}</h3>
                <Grafico alto={240} opcion={exceso} />
              </>
            )}
            <div className="cfg-nota faint">
              {t('pp = puntos porcentuales a favor (+) o en contra (−) de tu cartera. "Desde el inicio" puede depender de un solo evento; las ventanas móviles muestran si le ganás de forma consistente. Si después de varios años no le ganás a QQQ de forma sostenida, elegir acciones individuales te está costando rendimiento y trabajo.')}
            </div>
          </>
        )}
      </Card>

      <TirCuenta version={version} />

      <Mensual mensual={datos.mensual} unidad={nombreUnidad(datos.unidades.find((x) => x.id === u)?.nombre ?? "")} />

      <Contribucion unidad={u} version={version} />

      <Card titulo="Core vs. Satélite" sub="Cada bloque como si fuera una cartera propia · base 100 el día de su primera compra">
        {!categorias ? (
          <div className="vacio">{t("No hay datos suficientes por categoría.")}</div>
        ) : (
          <>
            <Grafico alto={320} opcion={categorias} />
            <table className="tabla">
              <thead>
                <tr>
                  <th>{t("Bloque")}</th>
                  <th>{t("Desde")}</th>
                  <th className="der">TWR</th>
                  <th className="der">{t("TWR anual")}</th>
                  <th className="der">{t("Ganancia")}</th>
                  <th className="der">{t("Peso hoy")}</th>
                </tr>
              </thead>
              <tbody>
                {datos.categorias.map((x, i) => (
                  <tr key={x.nombre}>
                    <td>
                      <span className="tk">
                        <i style={{ background: c.paleta[i % c.paleta.length] }} />
                        {t(x.nombre)}
                      </span>
                    </td>
                    <td className="muted">{fecha(x.desde)}</td>
                    <td className={`der ${signo(x.twr)}`}>{fpct(x.twr)}</td>
                    <td className={`der ${x.twr_anual == null ? "faint" : signo(x.twr_anual)}`}>{x.twr_anual == null ? t("menos de 1 año") : fpct(x.twr_anual)}</td>
                    <td className={`der ${signo(x.ganancia)}`}>{dinero(x.ganancia, u, true)}</td>
                    <td className="der">{num(x.peso, 1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="cfg-nota faint">
              {t('La categoría es la de tu configuración actual, aplicada a todo el historial. "Fuera de objetivo" son activos que tenés (o tuviste) pero que no están en tu cartera objetivo.')}
            </div>
          </>
        )}
      </Card>
    </>
  );
}
