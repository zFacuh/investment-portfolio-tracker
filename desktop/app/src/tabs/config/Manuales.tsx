import { useEffect, useState } from "react";
import { guardarManuales, type Config, type ManualCfg } from "../../api";
import { Card, Icono } from "../../components/ui";
import { t, tm } from "../../i18n";

const ICONO_BORRAR = "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3";

/**
 * Tenencias fuera de Cocos (otro broker, wallet propia...). Cada accion se
 * guarda al instante en data/manual_holdings.json, como en la app Streamlit.
 */
export function Manuales({ cfg, categorias, onGuardado }: { cfg: Config; categorias: string[]; onGuardado: () => Promise<void> }) {
  const [filas, setFilas] = useState<ManualCfg[]>(cfg.manuales);
  const [nuevo, setNuevo] = useState<ManualCfg>({ ticker: "", cantidad: null, categoria: cfg.categoria_fuera });
  const [ocupado, setOcupado] = useState(false);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; txt: string } | null>(null);

  useEffect(() => setFilas(cfg.manuales), [cfg.manuales]);

  const opciones = [...categorias, cfg.categoria_fuera];

  const persistir = async (lista: ManualCfg[], txt: string) => {
    setOcupado(true);
    setMensaje(null);
    try {
      await guardarManuales(lista);
      await onGuardado();
      setMensaje({ tipo: "ok", txt });
    } catch (e) {
      setMensaje({ tipo: "error", txt: (e as Error).message });
    } finally {
      setOcupado(false);
    }
  };

  const cambiada = (i: number) => JSON.stringify(filas[i]) !== JSON.stringify(cfg.manuales[i]);

  const agregar = () => {
    const tk = nuevo.ticker.trim().toUpperCase();
    if (!tk) return setMensaje({ tipo: "error", txt: t("El ticker no puede estar vacío.") });
    if (!nuevo.cantidad || nuevo.cantidad <= 0) return setMensaje({ tipo: "error", txt: t("La cantidad tiene que ser mayor a 0.") });
    persistir([...cfg.manuales, { ...nuevo, ticker: tk }], t("Se agregó {tk}.", { tk })).then(() =>
      setNuevo({ ticker: "", cantidad: null, categoria: cfg.categoria_fuera }),
    );
  };

  return (
    <Card titulo="Tenencias manuales" sub="Posiciones fuera de Cocos Capital: se suman a lo que sale del CSV. Cada cambio se guarda al instante.">
      {cfg.error_manuales && <div className="alerta error">{t("No se pudieron leer las tenencias guardadas: {e}", { e: tm(cfg.error_manuales) })}</div>}
      <div className="cfg-grid cfg-man cfg-head">
        <span>Ticker</span>
        <span className="der">{t("Cantidad")}</span>
        <span>{t("Categoría")}</span>
        <span />
      </div>
      {filas.length === 0 && <div className="vacio">{t("Todavía no cargaste ninguna tenencia manual.")}</div>}
      {filas.map((m, i) => (
        <div className="cfg-grid cfg-man" key={`${cfg.manuales[i]?.ticker}-${i}`}>
          <span className="mono tk-fijo">{m.ticker}</span>
          <input
            className="input der mono"
            type="number"
            min={0}
            step="any"
            value={m.cantidad ?? ""}
            onChange={(e) => setFilas((f) => f.map((x, j) => (j === i ? { ...x, cantidad: e.target.value === "" ? null : Number(e.target.value) } : x)))}
          />
          <select className="input" value={m.categoria} onChange={(e) => setFilas((f) => f.map((x, j) => (j === i ? { ...x, categoria: e.target.value } : x)))}>
            {!opciones.includes(m.categoria) && <option value={m.categoria}>{t(m.categoria)}</option>}
            {opciones.map((c) => (
              <option key={c} value={c}>
                {t(c)}
              </option>
            ))}
          </select>
          <div className="acciones-fila">
            {cambiada(i) && (
              <button
                className="btn-secundario chico"
                disabled={ocupado || !m.cantidad || m.cantidad <= 0}
                title={!m.cantidad || m.cantidad <= 0 ? t("Para sacarla, usá el botón de borrar") : undefined}
                onClick={() => persistir(filas.map((x, j) => (j === i ? x : cfg.manuales[j])), t("Se actualizó {tk}.", { tk: m.ticker }))}
              >
                {t("Guardar")}
              </button>
            )}
            <button
              className="btn-borrar"
              disabled={ocupado}
              title={t("Eliminar {tk}", { tk: m.ticker })}
              onClick={() => persistir(cfg.manuales.filter((_, j) => j !== i), t("Se eliminó {tk}.", { tk: m.ticker }))}
            >
              <Icono d={ICONO_BORRAR} size={15} />
            </button>
          </div>
        </div>
      ))}

      <h3>{t("Agregar una tenencia")}</h3>
      <div className="cfg-grid cfg-man">
        <input className="input mono" placeholder={t("Ej. GGAL, ETH")} value={nuevo.ticker} onChange={(e) => setNuevo({ ...nuevo, ticker: e.target.value.toUpperCase() })} />
        <input
          className="input der mono"
          type="number"
          min={0}
          step="any"
          placeholder={t("Cantidad")}
          value={nuevo.cantidad ?? ""}
          onChange={(e) => setNuevo({ ...nuevo, cantidad: e.target.value === "" ? null : Number(e.target.value) })}
          onKeyDown={(e) => e.key === "Enter" && agregar()}
        />
        <select className="input" value={nuevo.categoria} onChange={(e) => setNuevo({ ...nuevo, categoria: e.target.value })}>
          {opciones.map((c) => (
            <option key={c} value={c}>
              {t(c)}
            </option>
          ))}
        </select>
        <button className="btn-secundario chico" onClick={agregar} disabled={ocupado}>
          {t("Agregar")}
        </button>
      </div>
      <div className="cfg-nota faint">{t("Si el ticker no está en Activos, igual se cotiza y suma al valor total, pero con 0% objetivo (nunca recibe compras de la Calculadora DCA).")}</div>
      {mensaje && <div className={`alerta ${mensaje.tipo === "error" ? "error" : "ok"}`}>{tm(mensaje.txt)}</div>}
    </Card>
  );
}
