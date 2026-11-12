import type { Fila, Panel } from "../../api";
import { Card, Categoria, Signo, Tabla, Ticker, type Columna } from "../../components/ui";
import { ars, cantidad, pct } from "../../format";
import { useColoresTicker } from "../../theme/tema";
import { t } from "../../i18n";

export function Tenencia({ p }: { p: Panel }) {
  const colores = useColoresTicker(p.orden_tickers);
  const obj = new Map(p.objetivo.map((o) => [o.ticker, o.pct]));
  const n = (f: Fila, k: string) => f[k] as number | null;

  const columnas: Columna<Fila>[] = [
    { id: "t", nombre: "Activo", render: (f) => <Ticker t={f.Ticker as string} color={colores[f.Ticker as string]} />, orden: (f) => f.Ticker as string },
    { id: "cat", nombre: "Categoría", render: (f) => <Categoria c={f.Categoria as string} />, orden: (f) => f.Categoria as string },
    { id: "cant", nombre: "Cantidad", render: (f) => cantidad(n(f, "Cantidad")), orden: (f) => n(f, "Cantidad"), der: true },
    { id: "precio", nombre: "Precio ARS", render: (f) => ars(n(f, "Precio ARS"), 2), orden: (f) => n(f, "Precio ARS"), der: true },
    { id: "valor", nombre: "Valor ARS", render: (f) => ars(n(f, "Valor ARS")), orden: (f) => n(f, "Valor ARS"), der: true },
    { id: "real", nombre: "% Real", render: (f) => pct(n(f, "% Real")), orden: (f) => n(f, "% Real"), der: true },
    { id: "obj", nombre: "% Obj.", render: (f) => (obj.get(f.Ticker as string) ? pct(obj.get(f.Ticker as string)) : "—"), orden: (f) => obj.get(f.Ticker as string) ?? 0, der: true },
    { id: "pnl", nombre: "P&L ARS", render: (f) => <Signo v={n(f, "P&L ARS")} txt={ars(n(f, "P&L ARS"))} />, orden: (f) => n(f, "P&L ARS"), der: true },
    { id: "pnlp", nombre: "P&L %", render: (f) => <Signo v={n(f, "P&L %")} txt={pct(n(f, "P&L %"), 1, true)} />, orden: (f) => n(f, "P&L %"), der: true },
  ];

  return (
    <Card titulo="Tenencia actual" sub={t("{n} posiciones · clic en una columna para ordenar", { n: p.tenencia.length })}>
      <Tabla columnas={columnas} filas={p.tenencia} clave={(f) => f.Ticker as string} ordenInicial={{ id: "valor", asc: false }} />
    </Card>
  );
}
