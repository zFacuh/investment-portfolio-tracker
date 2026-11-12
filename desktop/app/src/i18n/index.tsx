/**
 * Idioma de la interfaz (español / inglés).
 *
 * El texto fuente esta escrito en español en el codigo y funciona como clave:
 *   t("Valor total (ARS)")              -> "Total value (ARS)" en ingles
 *   t("Te faltan {monto}", { monto })   -> interpola variables {asi}
 * Si una frase no esta en el diccionario, se muestra en español (nunca vacia).
 *
 * Los mensajes que llegan del backend / core/ (avisos, errores) pasan por
 * `tm()`, que ademas prueba patrones con partes variables (tickers, montos).
 *
 * Solo cambia lo que se MUESTRA: los valores internos (estados, categorias,
 * lo que se guarda en disco) siguen siendo los mismos en los dos idiomas.
 */
import { createContext, Fragment, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { EN } from "./en";
import { MENSAJES_FIJOS_EN, PATRONES_EN } from "./mensajes";

export type Idioma = "es" | "en";
const CLAVE = "fp-idioma";

function leer(): Idioma {
  // ?idioma=en|es fuerza el idioma (capturas de pantalla), igual que ?tema=.
  const url = new URLSearchParams(location.search).get("idioma");
  if (url === "en" || url === "es") return url;
  try {
    return localStorage.getItem(CLAVE) === "en" ? "en" : "es";
  } catch {
    return "es";
  }
}

// El idioma vive tambien a nivel modulo: t() se usa en funciones de formato y
// en opciones de graficos, fuera de React. Al cambiarlo, la app se vuelve a montar.
let actual: Idioma = leer();
document.documentElement.lang = actual;

export const idioma = () => actual;
/** Locale para Intl (numeros y fechas). */
export const locale = () => (actual === "en" ? "en-US" : "es-AR");

const interpolar = (s: string, vars?: Record<string, string | number | null | undefined>) =>
  vars ? s.replace(/\{(\w+)\}/g, (_, k: string) => (vars[k] == null ? "" : String(vars[k]))) : s;

/** Traduce una frase de la interfaz (la clave es el texto en español). */
export function t(es: string, vars?: Record<string, string | number | null | undefined>): string {
  if (actual === "es") return interpolar(es, vars);
  return interpolar(EN[es] ?? es, vars);
}

/** Como t(), pero las partes entre **asteriscos** salen en negrita. */
export function tb(es: string, vars?: Record<string, string | number | null | undefined>): ReactNode {
  return t(es, vars)
    .split("**")
    .map((parte, i) => (i % 2 ? <b key={i}>{parte}</b> : <Fragment key={i}>{parte}</Fragment>));
}

/** Traduce un mensaje que viene del backend: frase exacta o patron con partes variables. */
export function tm(mensaje: string): string {
  if (actual === "es" || !mensaje) return mensaje;
  // Errores de validacion juntados en un solo texto ("- uno\n- otro"): linea por linea.
  if (mensaje.includes("\n")) {
    return mensaje
      .split("\n")
      .map((l) => {
        const m = l.match(/^(\s*-\s+)(.*)$/);
        return m ? m[1] + traducirMensaje(m[2]) : traducirMensaje(l);
      })
      .join("\n");
  }
  return traducirMensaje(mensaje);
}

function traducirMensaje(mensaje: string): string {
  const exacto = EN[mensaje] ?? MENSAJES_FIJOS_EN[mensaje];
  if (exacto) return exacto;
  for (const [patron, reemplazo] of PATRONES_EN) {
    const m = mensaje.match(patron);
    if (!m) continue;
    return typeof reemplazo === "function" ? reemplazo(traducirMensaje, ...m.slice(1)) : mensaje.replace(patron, reemplazo);
  }
  return mensaje;
}

const Ctx = createContext<{ idioma: Idioma; setIdioma: (i: Idioma) => void } | null>(null);

export function IdiomaProvider({ children }: { children: (idioma: Idioma) => ReactNode }) {
  const [valor, setValor] = useState<Idioma>(actual);
  const setIdioma = useCallback((i: Idioma) => {
    actual = i;
    document.documentElement.lang = i;
    try {
      localStorage.setItem(CLAVE, i);
    } catch {
      /* sin storage: dura hasta cerrar */
    }
    setValor(i);
  }, []);
  const ctx = useMemo(() => ({ idioma: valor, setIdioma }), [valor, setIdioma]);
  return <Ctx.Provider value={ctx}>{children(valor)}</Ctx.Provider>;
}

export function useIdioma() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useIdioma fuera de IdiomaProvider");
  return c;
}
