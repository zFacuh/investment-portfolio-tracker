/**
 * Piezas de interfaz compartidas por todas las pestanas. No tienen colores
 * propios: todo sale de las clases de styles/app.css (que usan tokens).
 */
import { useState, type ReactNode } from "react";
import { ars } from "../format";
import { locale, t, tm } from "../i18n";
import { Cifra } from "./Cifra";

export function Icono({ d, size = 16 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

export function Card(props: { titulo?: string; sub?: string; acciones?: ReactNode; children: ReactNode; className?: string }) {
  const { titulo, sub, acciones, children, className } = props;
  return (
    <section className={`card ${className ?? ""}`}>
      {(titulo || acciones) && (
        <div className="card-head">
          <div>
            {titulo && <h2>{t(titulo)}</h2>}
            {sub && <div className="card-sub">{t(sub)}</div>}
          </div>
          {acciones}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi(props: { etiqueta: string; valor: string; delta?: number | null; deltaTxt?: string; sub?: string; tono?: "neg"; tooltip?: string }) {
  const { etiqueta, valor, delta, deltaTxt, sub, tono, tooltip } = props;
  return (
    <div className="card kpi" title={tooltip && t(tooltip)}>
      <div className="kpi-etq">{t(etiqueta)}</div>
      <div className={`kpi-val ${tono ?? ""}`}>
        <Cifra texto={valor} celdas />
      </div>
      {delta != null && deltaTxt && (
        <span className={`chip ${delta >= 0 ? "pos" : "neg"}`}>
          <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
            <path d={delta >= 0 ? "M5 1.5L9 8H1z" : "M5 8.5L1 2h8z"} fill="currentColor" />
          </svg>
          {deltaTxt}
        </span>
      )}
      {sub && <div className="kpi-sub">{t(sub)}</div>}
    </div>
  );
}

export function MiniKpi({ etq, val, fuerte, tooltip }: { etq: string; val: string; fuerte?: boolean; tooltip?: string }) {
  return (
    <div className={`mini ${fuerte ? "fuerte" : ""}`} title={tooltip && t(tooltip)}>
      <div className="mini-etq">{t(etq)}</div>
      <div className="mini-val">
        <Cifra texto={val} />
      </div>
    </div>
  );
}

export function Categoria({ c }: { c: string | null | undefined }) {
  const clase = c === "Core" ? "core" : c === "Satelite" ? "sat" : !c || c.startsWith("(") || c.startsWith("Cash") ? "muted" : "otra";
  // Las categorias del sistema se traducen; las del usuario (Core, Satelite...) se muestran tal cual.
  return <span className={`badge ${clase}`}>{c ? t(c) : t("N/D")}</span>;
}

export function Signo({ v, txt }: { v: number | null | undefined; txt: string }) {
  return <span className={v == null ? "faint" : v >= 0 ? "pos" : "neg"}>{txt}</span>;
}

export function Ticker({ t, color }: { t: string; color?: string }) {
  return (
    <span className="tk">
      <i style={{ background: color ?? "var(--cat-muted)" }} />
      {t}
    </span>
  );
}

export function Cargando({ texto, sub }: { texto: string; sub?: string }) {
  return (
    <div className="cargando">
      <div className="spinner" />
      <div>{t(texto)}</div>
      {sub && <div className="cargando-sub">{t(sub)}</div>}
    </div>
  );
}

export function Avisos({ avisos, titulo }: { avisos: string[]; titulo?: string }) {
  if (!avisos.length) return null;
  return (
    <details className="alerta">
      <summary>{titulo ? t(titulo) : t("{n} aviso(s) sobre los datos", { n: avisos.length })}</summary>
      <ul>
        {avisos.map((a) => (
          <li key={a}>{tm(a)}</li>
        ))}
      </ul>
    </details>
  );
}

export function Segmento<T extends string>(props: { opciones: { id: T; nombre: string; deshabilitado?: boolean; tooltip?: string }[]; valor: T; onChange: (v: T) => void }) {
  return (
    <div className="segmento">
      {props.opciones.map((o) => (
        <button key={o.id} className={props.valor === o.id ? "on" : ""} disabled={o.deshabilitado} title={o.tooltip && t(o.tooltip)} onClick={() => props.onChange(o.id)}>
          {t(o.nombre)}
        </button>
      ))}
    </div>
  );
}

/** Input de monto en pesos con separador de miles. */
export function MontoInput(props: { valor: number; onChange: (v: number) => void; onEnter?: () => void; chico?: boolean; prefijo?: string }) {
  return (
    <div className={`input-monto ${props.chico ? "chico" : ""}`}>
      <span>{props.prefijo ?? "$"}</span>
      <input
        inputMode="numeric"
        value={new Intl.NumberFormat(locale()).format(props.valor)}
        onChange={(e) => props.onChange(Number(e.target.value.replace(/\D/g, "")) || 0)}
        onKeyDown={(e) => e.key === "Enter" && props.onEnter?.()}
      />
    </div>
  );
}

export function MontosRapidos({ montos, valor, onChange }: { montos: number[]; valor: number; onChange: (v: number) => void }) {
  return (
    <div className="rapidos">
      {montos.map((m) => (
        <button key={m} className={valor === m ? "on" : ""} onClick={() => onChange(m)}>
          {ars(m)}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- Tabla
export interface Columna<F> {
  id: string;
  nombre: string;
  render: (f: F) => ReactNode;
  /** Valor para ordenar; sin esto la columna no es ordenable. */
  orden?: (f: F) => number | string | null | undefined;
  der?: boolean;
}

export function Tabla<F>(props: { columnas: Columna<F>[]; filas: F[]; clave: (f: F) => string; ordenInicial?: { id: string; asc: boolean } }) {
  const [orden, setOrden] = useState(props.ordenInicial ?? null);
  const col = props.columnas.find((c) => c.id === orden?.id);
  const filas =
    orden && col?.orden
      ? [...props.filas].sort((a, b) => {
          const x = col.orden!(a);
          const y = col.orden!(b);
          if (x == null) return 1;
          if (y == null) return -1;
          const r = typeof x === "string" ? x.localeCompare(String(y)) : x - (y as number);
          return orden.asc ? r : -r;
        })
      : props.filas;
  return (
    <div className="tabla-wrap">
      <table className="tabla">
        <thead>
          <tr>
            {props.columnas.map((c) => (
              <th
                key={c.id}
                className={`${c.der ? "der" : ""} ${c.orden ? "ordenable" : ""}`}
                onClick={c.orden ? () => setOrden((o) => ({ id: c.id, asc: o?.id === c.id ? !o.asc : false })) : undefined}
              >
                {t(c.nombre)}
                {orden?.id === c.id ? (orden.asc ? " ↑" : " ↓") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((f) => (
            <tr key={props.clave(f)}>
              {props.columnas.map((c) => (
                <td key={c.id} className={c.der ? "der" : ""}>
                  {c.render(f)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
