import type { Fila } from "../api";
import { ars, cantidad, num, pct, usd } from "../format";
import { Categoria } from "./ui";
import { Cifra } from "./Cifra";
import { t } from "../i18n";

/** Tarjeta de una orden sugerida (compra o venta), con el ticker a operar en Cocos. */
export function Orden({ o, tipo = "compra", marcar = false }: { o: Fila; tipo?: "compra" | "venta"; marcar?: boolean }) {
  const ejec = o["Ticker Ejecucion"] as string | null;
  const nominales = (tipo === "venta" ? o["Nominales a Vender"] : o["Nominales a Comprar"]) as number;
  const monto = (tipo === "venta" ? o["Monto Neto Venta ARS"] : o["Costo Total Estimado ARS"]) as number;
  const comision = o["Comision Estimada ARS"] as number | null;
  return (
    <div className={`orden ${marcar ? tipo : ""}`}>
      <div className="orden-1">
        <span className="orden-tk">
          {marcar && <span className={`badge ${tipo}`}>{tipo === "venta" ? t("Vender") : t("Comprar")}</span>}
          {ejec ?? o.Ticker}
          {ejec && ejec !== o.Ticker && <span className="faint"> {t("(obj. {tk})", { tk: o.Ticker })}</span>}
          <Categoria c={o.Categoria as string} />
        </span>
        <span className="orden-monto">
          <Cifra texto={ars(monto, 2)} />
        </span>
      </div>
      <div className="orden-meta">
        {t(nominales === 1 ? "{n} nominal · precio est. {p} {m}" : "{n} nominales · precio est. {p} {m}", { n: cantidad(nominales), p: num(o["Precio Actual"] as number), m: o.Moneda })}
        {o["Equivalente USD"] != null && <> · ≈ {usd(o["Equivalente USD"] as number, 2)}</>}
      </div>
      <div className="orden-meta faint">
        {t("{a} → objetivo {o}", { a: pct(o["% Actual"] as number), o: pct(o["% Objetivo"] as number) })}
        {comision ? <> · {tipo === "venta" ? t("neto de comisión est. {c}", { c: ars(comision, 2) }) : t("incluye comisión est. {c}", { c: ars(comision, 2) })}</> : null}
      </div>
    </div>
  );
}
