import { useTema } from "../theme/tema";

/**
 * Un numero de la interfaz. Con el gesto "cifras" (tema Anden) cada caracter es
 * una paleta de cartel de estacion: al cambiar el valor, los caracteres que
 * cambiaron dan vuelta uno tras otro, como un cartel de llegadas. La key de
 * cada caracter incluye el caracter, asi React solo re-anima los que cambiaron.
 */
export function Cifra({ texto, celdas = false }: { texto: string; celdas?: boolean }) {
  const { diseno } = useTema();
  if (diseno.gesto !== "cifras") return <>{texto}</>;
  return (
    <span className={`cifra ${celdas ? "con-celdas" : ""}`} aria-label={texto}>
      {[...texto].map((ch, i) => (
        <span key={`${i}:${ch}`} className={`flap ${/\d/.test(ch) ? "dig" : ""}`} style={{ animationDelay: `${i * 26}ms` }} aria-hidden="true">
          {ch}
        </span>
      ))}
    </span>
  );
}
