import { useEffect, useState, type ReactNode } from "react";
import { aHex, conAlfa, FAMILIAS, parseColor, type Diseno, type Familia } from "../theme/diseno";
import { useTema } from "../theme/tema";
import { Icono, Segmento } from "./ui";
import "./diseno-panel.css";
import { t } from "../i18n";

const ICONO_CERRAR = "M6 6l12 12M18 6L6 18";
const ICONO_BORRAR = "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3";
const ICONO_IZQ = "M15 6l-6 6 6 6";
const ICONO_DER = "M9 6l6 6-6 6";

/** Miniatura del tema, pintada con SUS colores (no con los del tema activo). */
function Miniatura({ d }: { d: Diseno }) {
  const c = d.colores;
  const fondo =
    d.fondo.tipo === "malla"
      ? `radial-gradient(circle at 15% 20%, ${d.fondo.malla[0]}, transparent 60%), radial-gradient(circle at 85% 30%, ${d.fondo.malla[1]}, transparent 60%), radial-gradient(circle at 60% 90%, ${d.fondo.malla[2]}, transparent 60%), ${c.bg}`
      : c.bg;
  const r = Math.min(d.forma.radioCard, 10);
  const superior = d.navegacion === "superior";
  return (
    <div className="mt-tema" style={{ background: fondo, flexDirection: superior ? "column" : "row" }}>
      <div
        className="mt-nav"
        style={{
          background: d.vidrio.activo ? c.surface : c.surface,
          borderColor: c.border,
          borderRadius: d.navegacion === "flotante" ? r : 0,
          margin: d.navegacion === "flotante" ? 4 : 0,
          width: superior ? "auto" : 22,
          height: superior ? 12 : "auto",
          backdropFilter: d.vidrio.activo ? "blur(8px)" : undefined,
        }}
      >
        <i style={{ background: c.accent }} />
      </div>
      <div className="mt-cuerpo">
        <div className="mt-kpis">
          {[0, 1, 2].map((i) => (
            <div key={i} style={{ background: c.surface, borderColor: c.border, borderRadius: r, backdropFilter: d.vidrio.activo ? "blur(8px)" : undefined }}>
              <b style={{ background: c.text, opacity: 0.85, fontFamily: FAMILIAS[d.tipografia.numeros].css }} />
              <s style={{ background: i === 1 ? c.neg : c.pos }} />
            </div>
          ))}
        </div>
        <div className="mt-card" style={{ background: c.surface, borderColor: c.border, borderRadius: r, backdropFilter: d.vidrio.activo ? "blur(8px)" : undefined }}>
          {c.chart.slice(0, 5).map((x, i) => (
            <span key={i} style={{ background: x, height: `${30 + ((i * 37) % 60)}%`, borderRadius: Math.min(d.forma.radioCtrl, 3) }} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Grupo({ titulo, children, abierto = false }: { titulo: string; children: ReactNode; abierto?: boolean }) {
  return (
    <details className="dp-grupo" open={abierto}>
      <summary>{t(titulo)}</summary>
      <div className="dp-grupo-cuerpo">{children}</div>
    </details>
  );
}

function Fila({ etq, valor, children }: { etq: string; valor?: string; children: ReactNode }) {
  return (
    <label className="dp-fila">
      <span className="dp-etq">
        {t(etq)}
        {valor && <b>{valor}</b>}
      </span>
      {children}
    </label>
  );
}

function Deslizador(p: { valor: number; min: number; max: number; paso?: number; onChange: (v: number) => void }) {
  return <input type="range" min={p.min} max={p.max} step={p.paso ?? 1} value={p.valor} onChange={(e) => p.onChange(Number(e.target.value))} />;
}

function Interruptor({ on, onChange, etq }: { on: boolean; onChange: (v: boolean) => void; etq: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={`dp-switch ${on ? "on" : ""}`} onClick={() => onChange(!on)}>
      <span className="dp-switch-pista">
        <span />
      </span>
      {t(etq)}
    </button>
  );
}

/** Color con selector; si el color tiene transparencia, agrega un deslizador de opacidad. */
function CampoColor({ etq, color, onChange, alfa = false }: { etq: string; color: string; onChange: (c: string) => void; alfa?: boolean }) {
  const a = parseColor(color)[3];
  return (
    <div className="dp-color">
      <input type="color" value={aHex(color)} onChange={(e) => onChange(alfa ? conAlfa(e.target.value, a) : e.target.value)} aria-label={t(etq)} />
      <span className="dp-color-etq">{t(etq)}</span>
      {alfa && (
        <span className="dp-color-alfa" title={t("Opacidad")}>
          <Deslizador valor={Math.round(a * 100)} min={2} max={100} onChange={(v) => onChange(conAlfa(color, v / 100))} />
          <b>{Math.round(a * 100)}%</b>
        </span>
      )}
    </div>
  );
}

export function DisenoPanel({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const { diseno: d, temas, sucio, elegir, editar, descartar, guardar, guardarComo, borrar } = useTema();
  const [nombre, setNombre] = useState("");
  const [nombrando, setNombrando] = useState(false);
  const [aBorrar, setABorrar] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  // Flechas izquierda/derecha: pasar de tema rapido para comparar (fuera de los campos).
  useEffect(() => {
    if (!abierto) return;
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.key === "Escape") onCerrar();
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const i = temas.findIndex((x) => x.id === d.id);
      const sig = temas[(i + (e.key === "ArrowRight" ? 1 : -1) + temas.length) % temas.length];
      elegir(sig.id);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [abierto, temas, d.id, elegir, onCerrar]);

  const paso = (dir: 1 | -1) => {
    const i = temas.findIndex((x) => x.id === d.id);
    elegir(temas[(i + dir + temas.length) % temas.length].id);
  };

  const confirmarGuardarComo = async () => {
    await guardarComo(nombre || t("{n} (mío)", { n: t(d.nombre) }));
    setNombrando(false);
    setNombre("");
    setAviso(t("Guardado como tema nuevo."));
  };

  const familias = Object.entries(FAMILIAS) as [Familia, { nombre: string }][];
  const ed = (f: (x: Diseno) => void) => {
    setAviso(null);
    editar(f);
  };

  return (
    <aside className={`dp ${abierto ? "abierto" : ""}`} aria-hidden={!abierto} aria-label={t("Diseño de la app")}>
      <header className="dp-head">
        <div>
          <h2>{t("Diseño")}</h2>
          <div className="card-sub">{t("Probá, ajustá y guardá. ← → cambia de tema.")}</div>
        </div>
        <button className="btn-icono" onClick={onCerrar} title={t("Cerrar (Esc)")}>
          <Icono d={ICONO_CERRAR} />
        </button>
      </header>

      <div className="dp-scroll">
        <div className="dp-actual">
          <button className="btn-icono" onClick={() => paso(-1)} title={t("Tema anterior")}>
            <Icono d={ICONO_IZQ} />
          </button>
          <div>
            <b>{t(d.nombre)}</b>
            <span>{t(d.descripcion)}</span>
          </div>
          <button className="btn-icono" onClick={() => paso(1)} title={t("Tema siguiente")}>
            <Icono d={ICONO_DER} />
          </button>
        </div>

        <div className="dp-temas">
          {temas.map((tema) => (
            <div key={tema.id} className={`dp-tema ${tema.id === d.id ? "activo" : ""}`}>
              <button className="dp-tema-btn" onClick={() => elegir(tema.id)} title={t(tema.descripcion)}>
                <Miniatura d={tema} />
                <span className="dp-tema-nombre">{t(tema.nombre)}</span>
              </button>
              {!tema.fabrica && (
                <button
                  className={`dp-tema-borrar ${aBorrar === tema.id ? "confirmar" : ""}`}
                  title={aBorrar === tema.id ? t("Clic de nuevo para borrar") : t("Borrar este tema")}
                  onClick={() => (aBorrar === tema.id ? (borrar(tema.id), setABorrar(null)) : setABorrar(tema.id))}
                  onBlur={() => setABorrar(null)}
                >
                  {aBorrar === tema.id ? t("¿Borrar?") : <Icono d={ICONO_BORRAR} size={13} />}
                </button>
              )}
            </div>
          ))}
        </div>

        <h3 className="dp-sub">{t("Personalizar")} {d.fabrica ? <span className="faint">{t("· los cambios se guardan como tema nuevo")}</span> : null}</h3>

        <Grupo titulo="Estructura" abierto>
          <Fila etq="Navegación">
            <Segmento valor={d.navegacion} onChange={(v) => ed((x) => (x.navegacion = v))} opciones={[{ id: "lateral", nombre: "Lateral" }, { id: "flotante", nombre: "Flotante" }, { id: "superior", nombre: "Superior" }]} />
          </Fila>
          <Fila etq="Densidad">
            <Segmento valor={d.densidad} onChange={(v) => ed((x) => (x.densidad = v))} opciones={[{ id: "compacta", nombre: "Compacta" }, { id: "normal", nombre: "Normal" }, { id: "amplia", nombre: "Amplia" }]} />
          </Fila>
          <Fila etq="Gesto propio">
            <Segmento
              valor={d.gesto}
              onChange={(v) => ed((x) => (x.gesto = v))}
              opciones={[
                { id: "ninguno", nombre: "Ninguno" },
                { id: "reflejo", nombre: "Vidrio", tooltip: "Los controles (segmentos, montos, botón principal) también son de vidrio" },
                { id: "cifras", nombre: "Cifras", tooltip: "Los números cambian dígito a dígito" },
                { id: "teclas", nombre: "Teclas", tooltip: "Botones como teclas físicas y visor oscuro" },
              ]}
            />
          </Fila>
          <Fila etq="Base">
            <Segmento valor={d.base} onChange={(v) => ed((x) => (x.base = v))} opciones={[{ id: "oscuro", nombre: "Oscura" }, { id: "claro", nombre: "Clara" }]} />
          </Fila>
        </Grupo>

        <Grupo titulo="Vidrio">
          <Interruptor etq="Paneles de vidrio" on={d.vidrio.activo} onChange={(v) => ed((x) => (x.vidrio.activo = v))} />
          <Interruptor etq="Refracción (el vidrio deforma el fondo)" on={d.vidrio.refraccion} onChange={(v) => ed((x) => (x.vidrio.refraccion = v))} />
          <Fila etq="Desenfoque" valor={`${d.vidrio.blur}px`}>
            <Deslizador valor={d.vidrio.blur} min={0} max={60} onChange={(v) => ed((x) => (x.vidrio.blur = v))} />
          </Fila>
          <Fila etq="Saturación" valor={`${d.vidrio.saturacion}%`}>
            <Deslizador valor={d.vidrio.saturacion} min={100} max={250} paso={5} onChange={(v) => ed((x) => (x.vidrio.saturacion = v))} />
          </Fila>
          <Fila etq="Brillo del borde" valor={`${Math.round(d.vidrio.brillo * 100)}%`}>
            <Deslizador valor={Math.round(d.vidrio.brillo * 100)} min={0} max={100} onChange={(v) => ed((x) => (x.vidrio.brillo = v / 100))} />
          </Fila>
        </Grupo>

        <Grupo titulo="Fondo">
          <Fila etq="Tipo">
            <Segmento
              valor={d.fondo.tipo}
              onChange={(v) => ed((x) => (x.fondo.tipo = v))}
              opciones={[
                { id: "solido", nombre: "Sólido" },
                { id: "malla", nombre: "Color" },
                { id: "mica", nombre: "Mica", tooltip: "Efecto de ventana de Windows 11 (solo en la app instalada)" },
                { id: "acrilico", nombre: "Acrílico", tooltip: "Vidrio de Windows 11 sobre tu escritorio (solo en la app instalada)" },
              ]}
            />
          </Fila>
          <CampoColor etq="Color base" color={d.colores.bg} onChange={(v) => ed((x) => (x.colores.bg = v))} />
          {d.fondo.tipo === "malla" && (
            <>
              <div className="dp-colores4">
                {d.fondo.malla.map((m, i) => (
                  <input key={i} type="color" value={aHex(m)} onChange={(e) => ed((x) => (x.fondo.malla[i] = e.target.value))} aria-label={t("Color {n} del fondo", { n: i + 1 })} />
                ))}
              </div>
              <Interruptor etq="Movimiento lento" on={d.fondo.animado} onChange={(v) => ed((x) => (x.fondo.animado = v))} />
              <Interruptor etq="Tono según el resultado del día" on={d.fondo.segunElDia} onChange={(v) => ed((x) => (x.fondo.segunElDia = v))} />
            </>
          )}
        </Grupo>

        <Grupo titulo="Colores">
          <CampoColor etq="Paneles" alfa color={d.colores.surface} onChange={(v) => ed((x) => (x.colores.surface = v))} />
          <CampoColor etq="Campos y controles" alfa color={d.colores.surface2} onChange={(v) => ed((x) => (x.colores.surface2 = v))} />
          <CampoColor etq="Bordes" alfa color={d.colores.border} onChange={(v) => ed((x) => (x.colores.border = v))} />
          <CampoColor etq="Texto" color={d.colores.text} onChange={(v) => ed((x) => (x.colores.text = v))} />
          <CampoColor etq="Texto secundario" color={d.colores.muted} onChange={(v) => ed((x) => (x.colores.muted = v))} />
          <CampoColor etq="Acento" color={d.colores.accent} onChange={(v) => ed((x) => ((x.colores.accent = v), (x.colores.lineaValor = v)))} />
          <CampoColor etq="Sube / ganancia" color={d.colores.pos} onChange={(v) => ed((x) => (x.colores.pos = v))} />
          <CampoColor etq="Baja / pérdida" color={d.colores.neg} onChange={(v) => ed((x) => (x.colores.neg = v))} />
          <CampoColor etq="Alerta" color={d.colores.warn} onChange={(v) => ed((x) => (x.colores.warn = v))} />
        </Grupo>

        <Grupo titulo="Forma">
          <Fila etq="Redondeo de paneles" valor={`${d.forma.radioCard}px`}>
            <Deslizador valor={d.forma.radioCard} min={0} max={32} onChange={(v) => ed((x) => (x.forma.radioCard = v))} />
          </Fila>
          <Fila etq="Redondeo de controles" valor={`${d.forma.radioCtrl}px`}>
            <Deslizador valor={d.forma.radioCtrl} min={0} max={20} onChange={(v) => ed((x) => (x.forma.radioCtrl = v))} />
          </Fila>
          <Fila etq="Grosor de borde" valor={`${d.forma.borde}px`}>
            <Deslizador valor={d.forma.borde} min={0} max={2} onChange={(v) => ed((x) => (x.forma.borde = v))} />
          </Fila>
          <Fila etq="Sombra">
            <Segmento valor={d.forma.sombra} onChange={(v) => ed((x) => (x.forma.sombra = v))} opciones={[{ id: "ninguna", nombre: "Ninguna" }, { id: "suave", nombre: "Suave" }, { id: "flotante", nombre: "Flotante" }]} />
          </Fila>
        </Grupo>

        <Grupo titulo="Tipografía">
          {(["cuerpo", "titulos", "numeros"] as const).map((k) => (
            <Fila key={k} etq={k === "cuerpo" ? "Texto" : k === "titulos" ? "Títulos" : "Números"}>
              <select className="input" value={d.tipografia[k]} onChange={(e) => ed((x) => (x.tipografia[k] = e.target.value as Familia))} style={{ fontFamily: FAMILIAS[d.tipografia[k]].css }}>
                {familias.map(([id, f]) => (
                  <option key={id} value={id}>
                    {f.nombre}
                  </option>
                ))}
              </select>
            </Fila>
          ))}
          <Fila etq="Peso de títulos" valor={String(d.tipografia.pesoTitulo)}>
            <Deslizador valor={d.tipografia.pesoTitulo} min={400} max={800} paso={50} onChange={(v) => ed((x) => (x.tipografia.pesoTitulo = v))} />
          </Fila>
          <Fila etq="Tamaño de los KPIs" valor={`${d.tipografia.tamKpi}px`}>
            <Deslizador valor={d.tipografia.tamKpi} min={20} max={44} onChange={(v) => ed((x) => (x.tipografia.tamKpi = v))} />
          </Fila>
          <Interruptor etq="Etiquetas en mayúsculas" on={d.tipografia.mayusculas} onChange={(v) => ed((x) => (x.tipografia.mayusculas = v))} />
        </Grupo>
      </div>

      <footer className={`dp-pie ${sucio ? "sucio" : ""}`}>
        {aviso && !sucio && <span className="dp-aviso">{aviso}</span>}
        {sucio && !nombrando && (
          <>
            <span className="dp-aviso">{t("Cambios sin guardar")}</span>
            <button className="btn-secundario chico" onClick={descartar}>
              {t("Descartar")}
            </button>
            {!d.fabrica && (
              <button className="btn-secundario chico" onClick={() => guardar().then(() => setAviso(t("Cambios guardados.")))}>
                {t("Guardar")}
              </button>
            )}
            <button className="btn-primario chico" onClick={() => (setNombrando(true), setNombre(t("{n} (mío)", { n: t(d.nombre) })))}>
              {t("Guardar como nuevo")}
            </button>
          </>
        )}
        {nombrando && (
          <div className="dp-nombre">
            <input className="input" autoFocus value={nombre} onChange={(e) => setNombre(e.target.value)} onKeyDown={(e) => e.key === "Enter" && confirmarGuardarComo()} placeholder={t("Nombre del tema")} />
            <button className="btn-secundario chico" onClick={() => setNombrando(false)}>
              {t("Cancelar")}
            </button>
            <button className="btn-primario chico" onClick={confirmarGuardarComo}>
              {t("Guardar")}
            </button>
          </div>
        )}
        {!sucio && !aviso && <span className="dp-aviso faint">{t("Se guarda en config/diseno_escritorio.json")}</span>}
      </footer>
    </aside>
  );
}
