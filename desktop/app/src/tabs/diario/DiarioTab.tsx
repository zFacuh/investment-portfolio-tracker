import { useEffect, useState } from "react";
import { borrarDecision, getDiario, getOpcionesTransicion, postDecision, postTransicion, type Transicion } from "../../api";
import { Avisos, Card, Icono, MiniKpi, MontoInput, Segmento } from "../../components/ui";
import { useDatos } from "../../components/useDatos";
import { ars, cantidad, dinero, fecha, fpct, num } from "../../format";
import { t, tb, tm } from "../../i18n";
import "./diario.css";

const ICONO_BORRAR = "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3";

export function DiarioTab({ version }: { version: number }) {
  return (
    <>
      <PlanTransicion version={version} />
      <DiarioDecisiones version={version} />
    </>
  );
}

// ------------------------------------------------------------------ Plan de transicion
function PlanTransicion({ version }: { version: number }) {
  const { datos: opciones } = useDatos(getOpcionesTransicion, [version]);
  const [vender, setVender] = useState<string[] | null>(null);
  const [monto, setMonto] = useState(0);
  const [sobre, setSobre] = useState(false);
  const [res, setRes] = useState<Transicion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [calculando, setCalculando] = useState(false);

  // Por defecto: vender todo lo que esta fuera de la config (0% objetivo).
  useEffect(() => {
    if (opciones && vender == null) setVender(opciones.fuera);
  }, [opciones, vender]);

  useEffect(() => {
    if (vender == null) return;
    setCalculando(true);
    const espera = setTimeout(() => {
      postTransicion(vender, monto, sobre)
        .then((r) => (setRes(r), setError(null)))
        .catch((e) => (setRes(null), setError((e as Error).message)))
        .finally(() => setCalculando(false));
    }, 300);
    return () => clearTimeout(espera);
  }, [vender, monto, sobre, version]);

  const alternar = (tk: string) => setVender((v) => (v ?? []).includes(tk) ? v!.filter((x) => x !== tk) : [...(v ?? []), tk]);
  const stress = res && Array.isArray(res.stress) ? res.stress : null;
  const colorDesvio = (d: number) => (Math.abs(d) <= 2 ? "pos" : Math.abs(d) <= 5 ? "warn" : "neg");

  return (
    <Card titulo="Plan de transición" sub="Vender lo que está fuera de tu objetivo y reinvertir en tu cartera objetivo" acciones={calculando ? <div className="spinner chico" /> : undefined}>
      <div className="alerta">
        {tb("Vender puede tener **impacto impositivo** (según tu situación fiscal y el tipo de activo) que este plan no calcula. Las comisiones son estimadas. Confirmá antes de ejecutar.")}
      </div>

      <h3>{t("Qué vender (posición completa) · clic para sumar o sacar")}</h3>
      <div className="chips">
        {opciones?.tickers.map((tk) => (
          <button key={tk} className={`chip-tk ${vender?.includes(tk) ? "on" : ""} ${opciones.fuera.includes(tk) ? "fuera" : ""}`} onClick={() => alternar(tk)} title={opciones.fuera.includes(tk) ? t("Fuera de tu objetivo (0%)") : t("Está en tu objetivo")}>
            {tk}
          </button>
        ))}
      </div>
      <div className="trans-ctrl">
        <label className="campo">
          <span>{t("Aporte nuevo para sumar (opcional)")}</span>
          <MontoInput chico valor={monto} onChange={setMonto} />
        </label>
        <label className="check">
          <input type="checkbox" checked={sobre} onChange={(e) => setSobre(e.target.checked)} />
          <span>
            {tb("Vender también el excedente de los activos que están **por encima** de su objetivo")}
            <span className="faint"> {t("(si no, el DCA los va equilibrando)")}</span>
          </span>
        </label>
      </div>

      {error && <div className="alerta error">{tm(error)}</div>}
      {res && (
        <>
          <div className="mini-kpis cuatro" style={{ marginTop: 16 }}>
            <MiniKpi etq="Ventas (neto)" val={ars(res.ventas_neto)} tooltip={`≈ ${dinero(res.ventas_neto_usd, "usd")}`} />
            <MiniKpi etq="Para reinvertir" val={ars(res.para_reinvertir)} fuerte tooltip="Neto de las ventas más el aporte nuevo." />
            <MiniKpi etq="Comisiones estimadas" val={ars(res.comisiones)} tooltip={t("≈ {u} · ventas + compras", { u: dinero(res.comisiones_usd, "usd", false, 2) })} />
            <MiniKpi etq="Vuelto" val={ars(res.vuelto)} tooltip="Lo que queda sin invertir por comprar nominales enteros." />
          </div>

          <div className="grid-2-par" style={{ marginTop: 6 }}>
            <div>
              <h3>{t("1. Ventas")}</h3>
              {res.ventas.length === 0 ? (
                <div className="vacio">{t("No hay ventas en este plan.")}</div>
              ) : (
                <table className="tabla">
                  <thead>
                    <tr>
                      <th>{t("Activo")}</th>
                      <th>{t("Motivo")}</th>
                      <th className="der">{t("Nominales")}</th>
                      <th className="der">{t("Neto")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {res.ventas.map((v) => (
                      <tr key={v.ticker}>
                        <td>
                          <span className="badge venta">{t("Vender")}</span> <b>{v.ticker}</b>
                        </td>
                        <td className="muted">{tm(v.motivo)}</td>
                        <td className="der">{cantidad(v.nominales)}</td>
                        <td className="der" title={t("≈ {u} · precio {p}", { u: dinero(v.usd, "usd", false, 2), p: ars(v.precio) })}>{ars(v.neto)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div>
              <h3>{t("2. Compras")}</h3>
              {res.compras.length === 0 ? (
                <div className="vacio">{t("No hay compras: sin efectivo para reinvertir, o no alcanza para un nominal.")}</div>
              ) : (
                <table className="tabla">
                  <thead>
                    <tr>
                      <th>{t("Activo")}</th>
                      <th className="der">{t("Nominales")}</th>
                      <th className="der">{t("Precio")}</th>
                      <th className="der">{t("Costo total")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {res.compras.map((v) => (
                      <tr key={v.ticker}>
                        <td>
                          <span className="badge compra">{t("Comprar")}</span> <b>{v.ticker}</b>
                        </td>
                        <td className="der">{cantidad(v.nominales)}</td>
                        <td className="der">{ars(v.precio)}</td>
                        <td className="der" title={`≈ ${dinero(v.usd, "usd", false, 2)}`}>{ars(v.costo)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="grid-2-par">
            <div>
              <h3>{t("3. Antes y después, por categoría")}</h3>
              <table className="tabla">
                <thead>
                  <tr>
                    <th>{t("Categoría")}</th>
                    <th className="der">{t("Hoy")}</th>
                    <th className="der">{t("Después")}</th>
                    <th className="der">{t("Objetivo")}</th>
                    <th className="der">{t("Desvío final")}</th>
                  </tr>
                </thead>
                <tbody>
                  {res.categorias.map((k) => {
                    const d = (k.despues ?? 0) - (k.objetivo ?? 0);
                    return (
                      <tr key={k.nombre}>
                        <td>{t(k.nombre)}</td>
                        <td className="der">{num(k.antes, 1)}%</td>
                        <td className="der">
                          <b>{num(k.despues, 1)}%</b>
                        </td>
                        <td className="der">{num(k.objetivo, 1)}%</td>
                        <td className={`der ${colorDesvio(d)}`}>
                          {d > 0 ? "+" : ""}
                          {num(d, 1)} pp
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div>
              <h3>{t("4. Cuánto caería en una crisis")}</h3>
              {res.stress && !Array.isArray(res.stress) && <div className="vacio">{tm(res.stress.error)}</div>}
              {stress && (
                <table className="tabla">
                  <thead>
                    <tr>
                      <th>{t("Escenario")}</th>
                      <th className="der">{t("Hoy")}</th>
                      <th className="der">{t("Después")}</th>
                      <th className="der">{t("Objetivo")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stress.map((s) => (
                      <tr key={s.nombre}>
                        <td>{t(s.nombre)}</td>
                        <td className="der neg">{fpct(s.hoy)}</td>
                        <td className="der neg">
                          <b>{fpct(s.despues)}</b>
                        </td>
                        <td className="der neg">{fpct(s.objetivo)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="cfg-nota faint">{t("Mismos escenarios que en la pestaña Riesgo (detalle y supuestos ahí).")}</div>
            </div>
          </div>
          <Avisos avisos={res.advertencias} titulo={t("{n} aclaración(es) sobre este plan", { n: res.advertencias.length })} />
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ Diario de decisiones
function DiarioDecisiones({ version }: { version: number }) {
  const [vers, setVers] = useState(0);
  const { datos, error } = useDatos(getDiario, [version, vers]);
  const [ticker, setTicker] = useState("");
  const [accion, setAccion] = useState("Venta");
  const [horizonte, setHorizonte] = useState(6);
  const [motivo, setMotivo] = useState("");
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; txt: string } | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [aBorrar, setABorrar] = useState<string | null>(null);

  const guardar = async () => {
    const tk = ticker.trim().toUpperCase();
    if (!tk) return setMensaje({ tipo: "error", txt: t("Falta el activo.") });
    setGuardando(true);
    try {
      await postDecision({ ticker: tk, accion, motivo, horizonte_meses: horizonte });
      setMensaje({ tipo: "ok", txt: t("Decisión sobre {tk} guardada. Volvé a mirarla en {n} meses.", { tk, n: horizonte }) });
      setTicker("");
      setMotivo("");
      setVers((v) => v + 1);
    } catch (e) {
      setMensaje({ tipo: "error", txt: (e as Error).message });
    } finally {
      setGuardando(false);
    }
  };

  const borrar = async (id: string) => {
    if (aBorrar !== id) return setABorrar(id); // primer clic: pide confirmacion
    try {
      await borrarDecision(id);
      setABorrar(null);
      setVers((v) => v + 1);
    } catch (e) {
      setMensaje({ tipo: "error", txt: (e as Error).message });
    }
  };

  const ref = datos?.referencia ?? "SPY";
  const claseResultado = (r: string) => (r === "Acierto" ? "compra" : r === "Error" ? "venta" : "muted");

  return (
    <Card titulo="Diario de decisiones" sub="Anotá el porqué de cada decisión fuera del DCA y mirá cómo salió">
      <div className="diario-form">
        <label className="campo">
          <span>{t("Activo")}</span>
          <input className="input mono" list="diario-tickers" placeholder={t("Ej. MSTR")} value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} />
          <datalist id="diario-tickers">
            {datos?.opciones.map((o) => (
              <option key={o} value={o} />
            ))}
          </datalist>
        </label>
        <label className="campo">
          <span>{t("Decisión")}</span>
          <Segmento valor={accion} onChange={setAccion} opciones={(datos?.acciones ?? ["Compra", "Venta", "Mantener"]).map((a) => ({ id: a, nombre: a }))} />
        </label>
        <label className="campo">
          <span>{t("Revisar en (meses)")}</span>
          <input className="input mono" type="number" min={1} max={120} value={horizonte} onChange={(e) => setHorizonte(Math.max(1, Number(e.target.value) || 1))} />
        </label>
        <label className="campo diario-motivo">
          <span>{t("Por qué")}</span>
          <textarea className="input" rows={2} placeholder={t("Ej: vendo MSTR porque ya tengo bitcoin vía IBIT y duplica el riesgo de la cartera.")} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </label>
        <button className="btn-primario angosto" onClick={guardar} disabled={guardando || !ticker.trim()}>
          {guardando ? t("Guardando…") : t("Guardar decisión")}
        </button>
      </div>
      {mensaje && <div className={`alerta ${mensaje.tipo === "error" ? "error" : "ok"}`} style={{ marginTop: 10 }}>{tm(mensaje.txt)}</div>}
      {error && <div className="alerta error">{tm(error)}</div>}

      {datos && datos.total === 0 && (
        <div className="vacio">
          {t("Todavía no anotaste decisiones. Empezá con las ventas de tu plan de transición: dentro de unos meses vas a poder ver, en dólares y contra {ref}, si vender cada una fue buena idea.", { ref })}
        </div>
      )}
      {datos && datos.total > 0 && (
        <>
          <div className="mini-kpis cuatro" style={{ marginTop: 16 }}>
            <MiniKpi etq="Decisiones anotadas" val={String(datos.total)} />
            <MiniKpi etq="Evaluables" val={String(datos.evaluables)} tooltip="Con precio y al menos 30 días de antigüedad." />
            <MiniKpi etq="Aciertos" val={datos.aciertos == null ? t("N/D") : `${num(datos.aciertos, 0)}%`} fuerte tooltip={t("Compra/Mantener: le ganó a {ref} desde ese día. Venta: rindió MENOS que {ref} después de vender.", { ref })} />
            <MiniKpi etq="Para revisar" val={String(datos.revisar)} tooltip="Ya pasó el horizonte que te pusiste." />
          </div>
          <div className="tabla-wrap">
            <table className="tabla diario-tabla">
              <thead>
                <tr>
                  <th>{t("Fecha")}</th>
                  <th>{t("Decisión")}</th>
                  <th>{t("Motivo")}</th>
                  <th className="der">{t("Activo (USD)")}</th>
                  <th className="der">{ref} (USD)</th>
                  <th className="der">{t("Diferencia")}</th>
                  <th>{t("Resultado")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {datos.entradas.map((e) => (
                  <tr key={e.id}>
                    <td className="muted">
                      {fecha(e.fecha)}
                      <div className="faint">{t("{n} días", { n: e.dias })}</div>
                    </td>
                    <td>
                      <span className={`badge ${e.accion === "Venta" ? "venta" : e.accion === "Compra" ? "compra" : "muted"}`}>{t(e.accion)}</span> <b>{e.ticker}</b>
                    </td>
                    <td className="motivo">{e.motivo || <span className="faint">—</span>}</td>
                    <td className="der">{e.activo_usd == null ? "—" : `${e.activo_usd > 0 ? "+" : ""}${num(e.activo_usd, 1)}%`}</td>
                    <td className="der">{e.ref_usd == null ? "—" : `${e.ref_usd > 0 ? "+" : ""}${num(e.ref_usd, 1)}%`}</td>
                    <td className="der">{e.diferencia == null ? "—" : `${e.diferencia > 0 ? "+" : ""}${num(e.diferencia, 1)} pp`}</td>
                    <td>
                      <span className={`badge ${claseResultado(e.resultado)}`}>{t(e.resultado)}</span>
                      {e.revisar && <span className="badge otra" style={{ marginLeft: 6 }}>{t("revisar")}</span>}
                    </td>
                    <td className="der">
                      <button className={`btn-borrar ${aBorrar === e.id ? "confirmar" : ""}`} title={aBorrar === e.id ? t("Clic de nuevo para borrar") : t("Borrar esta decisión")} onClick={() => borrar(e.id)} onBlur={() => setABorrar(null)}>
                        {aBorrar === e.id ? t("¿Borrar?") : <Icono d={ICONO_BORRAR} size={15} />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="cfg-nota faint">
        {t("Todo se mide en dólares (CCL del día de la decisión y de hoy) contra {ref}, que es la alternativa de no hacer nada especial. Se guarda en data/diario.json.", { ref })}
      </div>
    </Card>
  );
}
