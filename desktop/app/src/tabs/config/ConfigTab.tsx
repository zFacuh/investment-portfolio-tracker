import { useCallback, useEffect, useMemo, useState } from "react";
import { getConfig, guardarConfig, validarConfig, type ActivoCfg, type CategoriaCfg, type Config } from "../../api";
import { Cargando, Card, Icono } from "../../components/ui";
import { fecha, num } from "../../format";
import { t, tb, tm } from "../../i18n";
import { Manuales } from "./Manuales";
import { TusDatos } from "./TusDatos";
import "./config.css";

const ICONO_BORRAR = "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3";
const ICONO_MAS = "M12 5v14M5 12h14";

type Borrador = { categorias: CategoriaCfg[]; activos: ActivoCfg[] };

const n = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? 0 : v);
const cerca100 = (v: number, tol: number) => Math.abs(v - 100) <= tol;

/**
 * Configuracion: categorias y activos se editan en un borrador y se guardan
 * juntos (validados por El Guardian de core/config_manager.py en vivo);
 * las tenencias manuales se guardan al instante, igual que en Streamlit.
 */
export function ConfigTab({ onGuardado }: { onGuardado: () => void }) {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [borrador, setBorrador] = useState<Borrador | null>(null);
  const [errores, setErrores] = useState<string[]>([]);
  const [validando, setValidando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; txt: string } | null>(null);

  const cargar = useCallback(async () => {
    const c = await getConfig();
    setCfg(c);
    setBorrador({ categorias: c.categorias, activos: c.activos });
  }, []);

  useEffect(() => {
    cargar().catch((e) => setMensaje({ tipo: "error", txt: (e as Error).message }));
  }, [cargar]);

  const sucio = useMemo(
    () => !!cfg && !!borrador && JSON.stringify({ categorias: cfg.categorias, activos: cfg.activos }) !== JSON.stringify(borrador),
    [cfg, borrador],
  );

  // Validacion en vivo con las reglas de core/ (no se duplican en el frontend).
  useEffect(() => {
    if (!borrador) return;
    setValidando(true);
    const espera = setTimeout(async () => {
      try {
        setErrores((await validarConfig(borrador)).errores);
      } catch (e) {
        setErrores([(e as Error).message]);
      } finally {
        setValidando(false);
      }
    }, 300);
    return () => clearTimeout(espera);
  }, [borrador]);

  if (!cfg || !borrador) return mensaje ? <div className="alerta error">{tm(mensaje.txt)}</div> : <Cargando texto="Leyendo la configuración…" />;

  const tol = cfg.tolerancia;
  const sumaCat = borrador.categorias.reduce((s, c) => s + n(c.objetivo), 0);
  const nombresCat = borrador.categorias.map((c) => c.nombre.trim()).filter(Boolean);

  // --- mutaciones del borrador
  const setCat = (i: number, cambios: Partial<CategoriaCfg>) =>
    setBorrador((b) => {
      if (!b) return b;
      const viejo = b.categorias[i].nombre;
      const categorias = b.categorias.map((c, j) => (j === i ? { ...c, ...cambios } : c));
      // Renombrar una categoria arrastra a sus activos (si no, quedarian huerfanos).
      const activos =
        cambios.nombre !== undefined && viejo.trim()
          ? b.activos.map((a) => (a.categoria === viejo ? { ...a, categoria: cambios.nombre! } : a))
          : b.activos;
      return { categorias, activos };
    });
  const borrarCat = (i: number) => setBorrador((b) => b && { ...b, categorias: b.categorias.filter((_, j) => j !== i) });
  const agregarCat = () => setBorrador((b) => b && { ...b, categorias: [...b.categorias, { nombre: "", objetivo: 0, descripcion: "" }] });

  const setAct = (i: number, cambios: Partial<ActivoCfg>) =>
    setBorrador((b) => b && { ...b, activos: b.activos.map((a, j) => (j === i ? { ...a, ...cambios } : a)) });
  const borrarAct = (i: number) => setBorrador((b) => b && { ...b, activos: b.activos.filter((_, j) => j !== i) });
  const agregarAct = (categoria: string) =>
    setBorrador(
      (b) =>
        b && {
          ...b,
          activos: [...b.activos, { ticker: "", nombre: "", categoria, tipo: cfg.tipos[0] ?? "CEDEAR", objetivo_cat: 0, ticker_mercado: "", alias: "" }],
        },
    );

  const descartar = () => {
    setBorrador({ categorias: cfg.categorias, activos: cfg.activos });
    setMensaje(null);
  };

  const guardar = async () => {
    setGuardando(true);
    setMensaje(null);
    try {
      await guardarConfig(borrador);
      await cargar();
      setMensaje({ tipo: "ok", txt: t("Configuración guardada. Recalculando el panel con los nuevos objetivos…") });
      onGuardado();
    } catch (e) {
      setMensaje({ tipo: "error", txt: (e as Error).message });
    } finally {
      setGuardando(false);
    }
  };

  // Grupos de activos: uno por categoria (en el orden de la tabla) + los que apuntan a una categoria inexistente.
  const grupos = [
    ...nombresCat.map((nombre) => ({ nombre, valida: true })),
    ...[...new Set(borrador.activos.map((a) => a.categoria.trim()))].filter((c) => !nombresCat.includes(c)).map((nombre) => ({ nombre, valida: false })),
  ];
  const pctCat = new Map(borrador.categorias.map((c) => [c.nombre.trim(), n(c.objetivo)]));

  return (
    <>
      <TusDatos />
      <Card
        titulo="Categorías"
        sub="Bloques de la cartera y su peso objetivo sobre el total"
        acciones={<Suma valor={sumaCat} tol={tol} etiqueta="Total" />}
      >
        <div className="cfg-grid cfg-cat cfg-head">
          <span>{t("Categoría")}</span>
          <span className="der">{t("% objetivo")}</span>
          <span>{t("Descripción")}</span>
          <span />
        </div>
        {borrador.categorias.map((c, i) => (
          <div className="cfg-grid cfg-cat" key={i}>
            <input className="input" value={c.nombre} placeholder={t("Ej. Core")} onChange={(e) => setCat(i, { nombre: e.target.value })} />
            <PctInput valor={c.objetivo} onChange={(v) => setCat(i, { objetivo: v })} />
            <input className="input" value={c.descripcion} placeholder={t("Opcional")} onChange={(e) => setCat(i, { descripcion: e.target.value })} />
            <button className="btn-borrar" title={t("Borrar la categoría {c}", { c: c.nombre })} onClick={() => borrarCat(i)}>
              <Icono d={ICONO_BORRAR} size={15} />
            </button>
          </div>
        ))}
        <button className="btn-link" onClick={agregarCat}>
          <Icono d={ICONO_MAS} size={14} /> {t("Agregar categoría")}
        </button>
        <div className="barra-cats">
          {borrador.categorias.map((c, i) => (
            <div key={i} style={{ flex: Math.max(n(c.objetivo), 0.001) }} title={`${c.nombre}: ${num(n(c.objetivo), 1)}%`}>
              <span>{c.nombre || "—"}</span> {num(n(c.objetivo), 1)}%
            </div>
          ))}
        </div>
      </Card>

      <Card titulo="Activos" sub="Instrumentos y su peso dentro de cada categoría. El % del total se calcula solo.">
        {grupos.map((g) => {
          const filas = borrador.activos.map((a, i) => ({ a, i })).filter(({ a }) => a.categoria.trim() === g.nombre);
          const suma = filas.reduce((s, { a }) => s + n(a.objetivo_cat), 0);
          return (
            <div className="grupo" key={g.nombre || "(vacía)"}>
              <div className="grupo-head">
                <div>
                  <b>{g.nombre || t("(sin categoría)")}</b>
                  {g.valida ? <span className="faint"> · {t("{p}% del total", { p: num(pctCat.get(g.nombre) ?? 0, 1) })}</span> : <span className="warn"> · {t("esta categoría no existe")}</span>}
                </div>
                <Suma valor={suma} tol={tol} etiqueta="Activos" />
              </div>
              <div className="cfg-grid cfg-act cfg-head">
                <span>Ticker</span>
                <span>{t("Nombre")}</span>
                <span>{t("Categoría")}</span>
                <span className="der">{t("% en cat.")}</span>
                <span className="der">{t("% total")}</span>
                <span>{t("Ticker yfinance")}</span>
                <span>{t("Alias")}</span>
                <span />
              </div>
              {filas.map(({ a, i }) => (
                <div className="cfg-grid cfg-act" key={i}>
                  <input className="input mono" value={a.ticker} placeholder="TSLA" onChange={(e) => setAct(i, { ticker: e.target.value.toUpperCase() })} />
                  <input className="input" value={a.nombre} placeholder={t("Nombre")} onChange={(e) => setAct(i, { nombre: e.target.value })} />
                  <select className="input" value={a.categoria} onChange={(e) => setAct(i, { categoria: e.target.value })}>
                    {!nombresCat.includes(a.categoria) && <option value={a.categoria}>{a.categoria || t("(elegir)")}</option>}
                    {nombresCat.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <PctInput valor={a.objetivo_cat} onChange={(v) => setAct(i, { objetivo_cat: v })} />
                  <span className="der calc">{num(((pctCat.get(a.categoria.trim()) ?? 0) * n(a.objetivo_cat)) / 100, 2)}%</span>
                  <input className="input mono" value={a.ticker_mercado} placeholder="TSLA.BA" onChange={(e) => setAct(i, { ticker_mercado: e.target.value })} />
                  <input className="input mono" value={a.alias} placeholder="—" onChange={(e) => setAct(i, { alias: e.target.value.toUpperCase() })} />
                  <button className="btn-borrar" title={a.ticker ? t("Borrar {tk}", { tk: a.ticker }) : t("Borrar este activo")} onClick={() => borrarAct(i)}>
                    <Icono d={ICONO_BORRAR} size={15} />
                  </button>
                </div>
              ))}
              {g.valida && (
                <button className="btn-link" onClick={() => agregarAct(g.nombre)}>
                  <Icono d={ICONO_MAS} size={14} /> {t("Agregar activo a {c}", { c: g.nombre })}
                </button>
              )}
            </div>
          );
        })}
        <div className="cfg-nota">
          {tb("**Ticker yfinance**: el símbolo de yfinance para cotizar (ej. TSLA.BA; para BTC, IBIT.BA).")}{" "}
          {tb("**Alias**: otro ticker operable en Cocos; su posición se suma a este activo y las compras se calculan con su precio.")}
        </div>
        {cfg.ultima_actualizacion && <div className="cfg-nota faint">{t("Última actualización: {f} {h}", { f: fecha(cfg.ultima_actualizacion), h: cfg.ultima_actualizacion.slice(11, 16) })}</div>}
      </Card>

      <Manuales cfg={cfg} categorias={nombresCat} onGuardado={async () => { await cargar(); onGuardado(); }} />

      {mensaje && <div className={`alerta ${mensaje.tipo === "error" ? "error" : "ok"}`} style={{ whiteSpace: "pre-line" }}>{tm(mensaje.txt)}</div>}

      {(sucio || errores.length > 0) && (
        <div className={`barra-guardar ${errores.length ? "con-errores" : ""}`}>
          <div className="barra-guardar-txt">
            {errores.length ? (
              <details>
                <summary>
                  {tb(errores.length === 1 ? "**1 problema** antes de poder guardar" : "**{n} problemas** antes de poder guardar", { n: errores.length })}
                </summary>
                <ul>
                  {errores.map((e) => (
                    <li key={e}>{tm(e)}</li>
                  ))}
                </ul>
              </details>
            ) : (
              <span>
                <b>{t("Cambios sin guardar")}</b> · {validando ? t("validando…") : t("todo suma 100% y las categorías existen")}
              </span>
            )}
          </div>
          {sucio && (
            <>
              <button className="btn-secundario" onClick={descartar} disabled={guardando}>
                {t("Descartar")}
              </button>
              <button className="btn-primario angosto" onClick={guardar} disabled={guardando || validando || errores.length > 0}>
                {guardando ? t("Guardando…") : t("Guardar y recalcular")}
              </button>
            </>
          )}
        </div>
      )}
    </>
  );
}

function Suma({ valor, tol, etiqueta }: { valor: number; tol: number; etiqueta: string }) {
  const ok = cerca100(valor, tol);
  return (
    <span className={`suma ${ok ? "ok" : "mal"}`} title={ok ? t("Suma 100%") : t(valor > 100 ? "Tiene que sumar 100% (sobra {d} pp)" : "Tiene que sumar 100% (falta {d} pp)", { d: num(Math.abs(100 - valor), 1) })}>
      {t(etiqueta)}: {num(valor, 1)}% {ok ? "✓" : `· ${t(valor > 100 ? "sobra {d}" : "falta {d}", { d: num(Math.abs(100 - valor), 1) })}`}
    </span>
  );
}

function PctInput({ valor, onChange }: { valor: number | null; onChange: (v: number | null) => void }) {
  return (
    <div className="input pct">
      <input
        type="number"
        step={0.5}
        min={0}
        max={100}
        value={valor ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
      <span>%</span>
    </div>
  );
}
