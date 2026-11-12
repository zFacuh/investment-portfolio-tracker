import { useTema } from "../theme/tema";
import { conAlfa } from "../theme/diseno";

// Mapa de desplazamiento de la lente: gris neutro (128) en el centro; en la franja
// del borde el rojo/verde se apartan de 128 y empujan la imagen hacia afuera.
const SVG_LENTE = [
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none"><defs>',
  '<linearGradient id="x" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#000"/><stop offset=".14" stop-color="#800000"/><stop offset=".86" stop-color="#800000"/><stop offset="1" stop-color="#ff0000"/></linearGradient>',
  '<linearGradient id="y" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#000"/><stop offset=".14" stop-color="#008000"/><stop offset=".86" stop-color="#008000"/><stop offset="1" stop-color="#00ff00"/></linearGradient>',
  '</defs><rect width="100" height="100" fill="url(#x)"/><rect width="100" height="100" fill="url(#y)" style="mix-blend-mode:screen"/></svg>',
].join("");
const MAPA_LENTE = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(SVG_LENTE);

/**
 * Fondo de la ventana. En los temas de vidrio es un campo de color vivo detras
 * de los paneles (sin el, el vidrio no tiene nada que refractar). Con
 * "segun el dia", la mancha principal toma el color del resultado de la rueda:
 * verde si la cartera subio, rojo si bajo, con intensidad segun la magnitud.
 * Tambien define el filtro SVG de refraccion que usan los paneles de vidrio.
 */
export function Fondo() {
  const { diseno, tonoDelDia } = useTema();
  const f = diseno.fondo;
  const c = diseno.colores;
  const malla = [...f.malla];

  if (f.segunElDia && tonoDelDia != null) {
    // 2% de variacion diaria = tono pleno
    const fuerza = Math.min(Math.abs(tonoDelDia) / 0.02, 1);
    malla[0] = conAlfa(tonoDelDia >= 0 ? c.pos : c.neg, 0.22 + 0.3 * fuerza);
  }

  return (
    <>
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        {/* Lente en los bordes: mapa de normales (rojo = desplazamiento horizontal,
            verde = vertical), neutro en el centro, que dobla la imagen cerca del borde. */}
        {/* El mapa se estira al panel; el desplazamiento maximo es de 26px en ambos ejes. */}
        <filter id="fp-refraccion" x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
          <feImage href={MAPA_LENTE} preserveAspectRatio="none" result="mapa" />
          <feDisplacementMap in="SourceGraphic" in2="mapa" scale="26" xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </svg>
      {f.tipo === "malla" && (
        <div className={`fondo ${f.animado ? "animado" : ""}`} aria-hidden="true">
          {malla.map((color, i) => (
            <span key={i} className={`mancha m${i + 1}`} style={{ background: `radial-gradient(closest-side, ${color}, transparent)` }} />
          ))}
          <span className="velo" />
        </div>
      )}
    </>
  );
}
