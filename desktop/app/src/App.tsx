import { useCallback, useEffect, useState, type ReactNode } from "react";
import { esperarBackend, getCurva, getPanel, refrescar, type Curva, type Panel } from "./api";
import { DisenoPanel } from "./components/DisenoPanel";
import { Fondo } from "./components/Fondo";
import { Cargando, Icono } from "./components/ui";
import { useTema } from "./theme/tema";
import { locale, t, tm, useIdioma } from "./i18n";
import { ars } from "./format";
import { AportesTab } from "./tabs/aportes/AportesTab";
import { ConfigTab } from "./tabs/config/ConfigTab";
import { DiarioTab } from "./tabs/diario/DiarioTab";
import { MetasTab } from "./tabs/metas/MetasTab";
import { PanelTab } from "./tabs/panel/PanelTab";
import { RendimientoTab } from "./tabs/rendimiento/RendimientoTab";
import { RiesgoTab } from "./tabs/riesgo/RiesgoTab";

type SeccionId = "panel" | "rend" | "aportes" | "riesgo" | "metas" | "diario" | "config";

interface Seccion {
  id: SeccionId;
  nombre: string;
  titulo: string;
  icono: string;
  /** Contenido de la pestana; sin esto aparece como "pronto". */
  render?: (d: { panel: Panel; curva: Curva | null; recargar: () => void; version: number }) => ReactNode;
}

const SECCIONES: Seccion[] = [
  { id: "panel", nombre: "Panel", titulo: "Panel y rebalanceo", icono: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z", render: (d) => <PanelTab panel={d.panel} curva={d.curva} /> },
  { id: "rend", nombre: "Rendimiento", titulo: "Rendimiento", icono: "M3 17l6-6 4 4 8-8M15 7h6v6", render: (d) => <RendimientoTab version={d.version} /> },
  { id: "aportes", nombre: "Aportes", titulo: "Aportes y dividendos", icono: "M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6", render: (d) => <AportesTab version={d.version} /> },
  { id: "riesgo", nombre: "Riesgo", titulo: "Riesgo", icono: "M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6z", render: (d) => <RiesgoTab version={d.version} /> },
  { id: "metas", nombre: "Metas", titulo: "Metas", icono: "M4 22V4M4 4h12l-2 4 2 4H4", render: (d) => <MetasTab version={d.version} recargar={d.recargar} /> },
  { id: "diario", nombre: "Diario", titulo: "Transición y diario", icono: "M4 4h16v16H4zM8 8h8M8 12h8M8 16h5", render: (d) => <DiarioTab version={d.version} /> },
  { id: "config", nombre: "Configuración", titulo: "Configuración", icono: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M14 4v4M8 10v4M16 16v4", render: (d) => <ConfigTab onGuardado={d.recargar} /> },
];

export default function App() {
  const [listo, setListo] = useState(false);
  const [errorInicio, setErrorInicio] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [curva, setCurva] = useState<Curva | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // ?pestana=rend|riesgo|... abre directo esa pestana (capturas de pantalla).
  const [activa, setActiva] = useState<SeccionId>(() => {
    const p = new URLSearchParams(location.search).get("pestana");
    return SECCIONES.some((s) => s.id === p) ? (p as SeccionId) : "panel";
  });
  // Sube cada vez que se refrescan los datos: las pestanas que piden lo suyo vuelven a pedirlo.
  const [version, setVersion] = useState(0);
  // Pestanas ya visitadas: quedan montadas (ocultas) para no perder su estado al cambiar.
  const [visitadas, setVisitadas] = useState<Set<SeccionId>>(() => new Set(["panel", activa]));

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      setPanel(await getPanel());
      getCurva().then(setCurva).catch(() => setCurva(null));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    esperarBackend()
      .then(() => {
        setListo(true);
        cargar();
      })
      .catch((e) => setErrorInicio(e.message));
  }, [cargar]);

  // Boton de refresco: descarta todo lo cacheado y vuelve a descargar cotizaciones.
  const actualizar = async () => {
    setCurva(null);
    await refrescar();
    setVersion((v) => v + 1);
    await cargar();
  };

  // Despues de guardar algo (config, meta, tenencias): el backend ya invalido lo
  // que corresponde, asi que solo se vuelven a pedir los datos (sin re-descargar).
  const recargar = async () => {
    setVersion((v) => v + 1);
    await cargar();
  };

  const ir = (id: SeccionId) => {
    setActiva(id);
    setVisitadas((v) => new Set(v).add(id));
  };

  const seccion = SECCIONES.find((s) => s.id === activa)!;

  // Panel de Diseno: boton en la navegacion y atajo Ctrl+D.
  const [disenoAbierto, setDisenoAbierto] = useState(false);
  useEffect(() => {
    document.documentElement.dataset.panel = disenoAbierto ? "abierto" : "cerrado";
  }, [disenoAbierto]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") {
        e.preventDefault();
        setDisenoAbierto((v) => !v);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  // El fondo de los temas de vidrio toma el color del resultado del dia.
  const { setTonoDelDia } = useTema();
  useEffect(() => {
    const p = panel?.kpis.variacion.pct;
    setTonoDelDia(p == null ? null : p / 100);
  }, [panel, setTonoDelDia]);

  return (
    <>
    <Fondo />
    <div className="shell">
      <aside className="sidebar">
        <div className="marca">
          <div className="logo">IP</div>
          <div>
            <div className="marca-nombre">Investment Portfolio</div>
            <div className="marca-sub">Tracker · Cocos Capital</div>
          </div>
        </div>
        <nav className="nav">
          {SECCIONES.map((s) => (
            <button
              key={s.id}
              className={`nav-item ${s.id === activa ? "activo" : ""}`}
              disabled={!s.render}
              title={!s.render ? t("Próximamente en la app de escritorio") : undefined}
              onClick={() => ir(s.id)}
            >
              <Icono d={s.icono} />
              <span>{t(s.nombre)}</span>
              {!s.render && <span className="pronto">{t("pronto")}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-pie">
          <button className={`btn-diseno ${disenoAbierto ? "on" : ""}`} onClick={() => setDisenoAbierto((v) => !v)} title={t("Cambiar el diseño de la app (Ctrl+D)")}>
            <Icono d="M12 3a9 9 0 100 18c1.1 0 1.5-.8 1.5-1.6 0-.9-.6-1.4-.6-2.2 0-.9.7-1.5 1.6-1.5H17a4 4 0 004-4c0-4.8-4-8.7-9-8.7zM7.5 12.5h.01M9.5 8h.01M14.5 8h.01" />
            <span>{t("Diseño")}</span>
          </button>
          <SelectorIdioma />
          <div className="version">{t("Versión {v}", { v: "0.6" })}</div>
        </div>
      </aside>

      <main className="contenido">
        <header className="top">
          <h1>{t(seccion.titulo)}</h1>
          <div className="top-meta">
            <Meta etiqueta="Dólar CCL" valor={panel ? ars(panel.ccl, 2) : "—"} />
            <Meta etiqueta="Actualizado" valor={panel ? new Date(panel.actualizado).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" }) : "—"} />
            <button className="btn-icono" onClick={actualizar} disabled={!listo || cargando} title={t("Volver a descargar cotizaciones")}>
              <svg className={cargando ? "girando" : ""} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
                <path d="M21 12a9 9 0 11-3-6.7L21 8M21 3v5h-5" />
              </svg>
            </button>
          </div>
        </header>

        {errorInicio && <div className="alerta error">{tm(errorInicio)}</div>}
        {error && <div className="alerta error">{tm(error)}</div>}
        {!panel && !errorInicio && !error && (
          <Cargando
            texto={listo ? "Descargando cotizaciones y armando la tenencia…" : "Iniciando motor de datos…"}
            sub="La primera carga tarda unos segundos; después todo queda en memoria."
          />
        )}

        {panel &&
          SECCIONES.filter((s) => s.render && visitadas.has(s.id)).map((s) => (
            <div key={s.id} className="pagina" hidden={s.id !== activa}>
              {s.render!({ panel, curva, recargar, version })}
            </div>
          ))}
      </main>
    </div>
    <DisenoPanel abierto={disenoAbierto} onCerrar={() => setDisenoAbierto(false)} />
    </>
  );
}

function Meta({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div className="meta">
      <div className="meta-etq">{t(etiqueta)}</div>
      <div className="meta-val">{valor}</div>
    </div>
  );
}

/** Selector de idioma de la interfaz (se recuerda entre sesiones). */
function SelectorIdioma() {
  const { idioma, setIdioma } = useIdioma();
  return (
    <div className="idioma" role="group" aria-label={t("Idioma")}>
      {(["es", "en"] as const).map((i) => (
        <button key={i} className={idioma === i ? "on" : ""} onClick={() => setIdioma(i)} title={i === "es" ? "Español" : "English"}>
          {i.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
