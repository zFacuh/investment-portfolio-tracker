import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getDiseno, guardarDiseno } from "../api";
import { aplicarDiseno, clonar, conAlfa, DISENO_INICIAL, FABRICA, type Diseno } from "./diseno";

/**
 * Tema activo y laboratorio de diseno. Guarda en config/diseno_escritorio.json
 * (via backend) cual tema esta activo y los temas personalizados; una copia en
 * localStorage permite pintar el tema correcto al instante mientras arranca Python.
 */

export interface ColoresGrafico {
  text: string;
  muted: string;
  faint: string;
  surface: string;
  surface2: string;
  border: string;
  grid: string;
  tooltip: string;
  accent: string;
  pos: string;
  neg: string;
  warn: string;
  valor: string;
  capital: string;
  paleta: string[];
  bench: string[];
}

const colorGrafico = (d: Diseno): ColoresGrafico => ({
  text: d.colores.text,
  muted: d.colores.muted,
  faint: d.colores.faint,
  surface: d.colores.surface,
  surface2: d.colores.surface2,
  border: d.colores.border,
  grid: d.colores.grid,
  tooltip: d.colores.tooltip,
  accent: d.colores.accent,
  pos: d.colores.pos,
  neg: d.colores.neg,
  warn: d.colores.warn,
  valor: d.colores.lineaValor,
  capital: d.colores.lineaCapital,
  paleta: d.colores.chart,
  bench: d.colores.bench,
});

interface Estado {
  activo: string;
  personalizados: Diseno[];
}

interface Ctx {
  /** Diseno visible (incluye cambios sin guardar). */
  diseno: Diseno;
  temas: Diseno[];
  sucio: boolean;
  colores: ColoresGrafico;
  elegir: (id: string) => void;
  editar: (cambio: (d: Diseno) => void) => void;
  descartar: () => void;
  guardar: () => Promise<void>;
  guardarComo: (nombre: string) => Promise<void>;
  borrar: (id: string) => Promise<void>;
  /** Variacion del dia (fraccion) para el gesto "reflejo". */
  tonoDelDia: number | null;
  setTonoDelDia: (v: number | null) => void;
}

const CLAVE_CACHE = "fp-diseno";
const TemaCtx = createContext<Ctx | null>(null);

function leerCache(): Estado {
  // ?tema=<id> abre la app con ese tema sin guardarlo (sirve para capturas y comparar).
  const forzado = new URLSearchParams(location.search).get("tema");
  try {
    if (forzado) return { ...leerCacheLocal(), activo: forzado };
  } catch {
    /* sigue */
  }
  return leerCacheLocal();
}

function leerCacheLocal(): Estado {
  try {
    const x = JSON.parse(localStorage.getItem(CLAVE_CACHE) || "null");
    if (x && typeof x.activo === "string") return { activo: x.activo, personalizados: Array.isArray(x.personalizados) ? x.personalizados : [] };
  } catch {
    /* sin storage */
  }
  return { activo: DISENO_INICIAL, personalizados: [] };
}

function escribirCache(e: Estado) {
  try {
    localStorage.setItem(CLAVE_CACHE, JSON.stringify(e));
  } catch {
    /* sin storage */
  }
}

const buscar = (e: Estado, id: string) => [...FABRICA, ...e.personalizados].find((d) => d.id === id) ?? FABRICA[0];

/** Efectos de ventana de Windows 11 (Mica / Acrilico) cuando corre dentro de Tauri. */
async function efectoVentana(d: Diseno) {
  if (!("__TAURI_INTERNALS__" in window)) return;
  try {
    const { getCurrentWindow, Effect } = await import("@tauri-apps/api/window");
    const w = getCurrentWindow();
    await w.setTheme(d.base === "oscuro" ? "dark" : "light"); // barra de titulo de Windows
    if (d.fondo.tipo === "mica") await w.setEffects({ effects: [Effect.Mica] });
    else if (d.fondo.tipo === "acrilico") await w.setEffects({ effects: [Effect.Acrylic] });
    else await w.clearEffects();
  } catch {
    /* efecto no disponible: queda el fondo de la app */
  }
}

export function TemaProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<Estado>(leerCache);
  const [borrador, setBorrador] = useState<Diseno>(() => clonar(buscar(leerCache(), leerCache().activo)));
  const [tonoDelDia, setTonoDelDia] = useState<number | null>(null);
  const sincronizado = useRef(false);

  // Aplicar al DOM en cada cambio (sincronico: sin parpadeo).
  useEffect(() => {
    aplicarDiseno(borrador);
  }, [borrador]);
  useEffect(() => {
    efectoVentana(borrador);
  }, [borrador.fondo.tipo, borrador.base]); // eslint-disable-line react-hooks/exhaustive-deps

  // Al arrancar, traer lo guardado en disco (la cache local puede estar vieja).
  useEffect(() => {
    let intentos = 0;
    const traer = () =>
      getDiseno()
        .then((r) => {
          const forzado = new URLSearchParams(location.search).get("tema");
          const e: Estado = {
            activo: forzado ?? r.activo ?? estado.activo,
            personalizados: (r.personalizados as Diseno[]) ?? [],
          };
          sincronizado.current = true;
          setEstado(e);
          escribirCache(e);
          setBorrador(clonar(buscar(e, e.activo)));
        })
        .catch(() => {
          if (++intentos < 60) setTimeout(traer, 1000); // el backend todavia arranca
        });
    traer();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const persistir = useCallback(async (e: Estado) => {
    setEstado(e);
    escribirCache(e);
    await guardarDiseno(e.activo, e.personalizados);
  }, []);

  const guardado = buscar(estado, estado.activo);
  const sucio = JSON.stringify(guardado) !== JSON.stringify(borrador);

  const elegir = useCallback(
    (id: string) => {
      const e = { ...estado, activo: id };
      setBorrador(clonar(buscar(e, id)));
      persistir(e).catch(() => undefined);
    },
    [estado, persistir],
  );

  const editar = useCallback((cambio: (d: Diseno) => void) => {
    setBorrador((d) => {
      const x = clonar(d);
      cambio(x);
      return x;
    });
  }, []);

  const descartar = useCallback(() => setBorrador(clonar(guardado)), [guardado]);

  const guardar = useCallback(async () => {
    if (borrador.fabrica) return;
    const personalizados = estado.personalizados.map((d) => (d.id === borrador.id ? clonar(borrador) : d));
    await persistir({ activo: borrador.id, personalizados });
  }, [borrador, estado, persistir]);

  const guardarComo = useCallback(
    async (nombre: string) => {
      const nuevo: Diseno = { ...clonar(borrador), id: `propio-${Date.now().toString(36)}`, nombre: nombre.trim() || "Mi diseño", fabrica: false, descripcion: `Basado en ${borrador.nombre}.` };
      const e = { activo: nuevo.id, personalizados: [...estado.personalizados, nuevo] };
      setBorrador(clonar(nuevo));
      await persistir(e);
    },
    [borrador, estado, persistir],
  );

  const borrar = useCallback(
    async (id: string) => {
      const personalizados = estado.personalizados.filter((d) => d.id !== id);
      const activo = estado.activo === id ? DISENO_INICIAL : estado.activo;
      const e = { activo, personalizados };
      if (estado.activo === id) setBorrador(clonar(buscar(e, activo)));
      await persistir(e);
    },
    [estado, persistir],
  );

  // Los graficos se redibujan con un pequeno retardo mientras se arrastra un control.
  const [colores, setColores] = useState(() => colorGrafico(borrador));
  useEffect(() => {
    const t = setTimeout(() => setColores(colorGrafico(borrador)), 90);
    return () => clearTimeout(t);
  }, [borrador]);

  const valor = useMemo<Ctx>(
    () => ({
      diseno: borrador,
      temas: [...FABRICA, ...estado.personalizados],
      sucio,
      colores,
      elegir,
      editar,
      descartar,
      guardar,
      guardarComo,
      borrar,
      tonoDelDia,
      setTonoDelDia,
    }),
    [borrador, estado.personalizados, sucio, colores, elegir, editar, descartar, guardar, guardarComo, borrar, tonoDelDia],
  );
  return <TemaCtx.Provider value={valor}>{children}</TemaCtx.Provider>;
}

export function useTema() {
  const c = useContext(TemaCtx);
  if (!c) throw new Error("useTema fuera de TemaProvider");
  return c;
}

/** Color fijo por ticker (mismo orden en todas las vistas), desde la paleta del tema. */
export function useColoresTicker(tickers: string[]): Record<string, string> {
  const { colores } = useTema();
  return useMemo(() => Object.fromEntries(tickers.map((t, i) => [t, colores.paleta[i % colores.paleta.length]])), [tickers, colores]);
}

/** Tooltip de ECharts con el material del tema (vidrio esmerilado cuando corresponde). */
export function tooltipBase(c: ColoresGrafico) {
  return {
    backgroundColor: c.tooltip,
    borderColor: c.border,
    textStyle: { color: c.text },
    extraCssText: "backdrop-filter: blur(18px) saturate(160%); border-radius: 10px; box-shadow: 0 10px 30px -12px rgba(0,0,0,.45);",
  };
}

/** Color del tema + transparencia (acepta hex y rgba). */
export const alfa = (color: string, a: number) => conAlfa(color, a);
