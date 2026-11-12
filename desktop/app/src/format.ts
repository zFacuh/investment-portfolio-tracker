import { locale, t } from "./i18n";

const nfBase = (dec: number) => new Intl.NumberFormat(locale(), { minimumFractionDigits: dec, maximumFractionDigits: dec });
/** Formateador con el signo menos tipografico (U+2212): mismo ancho visual que el +, sin hueco. */
const nf = (dec: number) => ({ format: (v: number) => nfBase(dec).format(v).replace("-", "−") });

export const ars = (v: number | null | undefined, dec = 0) =>
  v == null ? t("N/D") : `$ ${nf(dec).format(v)}`;

export const usd = (v: number | null | undefined, dec = 0) =>
  v == null ? t("N/D") : `US$ ${nf(dec).format(v)}`;

export const pct = (v: number | null | undefined, dec = 1, signo = false) =>
  v == null ? t("N/D") : `${signo && v > 0 ? "+" : ""}${nf(dec).format(v)}%`;

export const num = (v: number | null | undefined, dec = 2) => (v == null ? t("N/D") : nf(dec).format(v));

export const cantidad = (v: number | null | undefined) =>
  v == null ? t("N/D") : new Intl.NumberFormat(locale(), { maximumFractionDigits: 8 }).format(v);

export const fecha = (iso: string | null | undefined) => {
  if (!iso) return t("N/D");
  const [a, m, d] = iso.slice(0, 10).split("-");
  return locale() === "en-US" ? `${m}/${d}/${a}` : `${d}/${m}/${a}`;
};

/** Monto en la unidad elegida (US$ para dolares, $ para pesos), opcionalmente con signo. */
export const dinero = (v: number | null | undefined, unidad: string, signo = false, dec = 0) => {
  if (v == null) return t("N/D");
  const pref = unidad === "usd" ? "US$ " : "$ ";
  const s = new Intl.NumberFormat(locale(), { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(Math.abs(v));
  return `${signo ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : ""}${pref}${s}`;
};

/** Fraccion (0.153) como porcentaje con signo (+15,3%). */
export const fpct = (v: number | null | undefined, dec = 1) => pct(v == null ? null : v * 100, dec, true);

/** Fraccion como puntos porcentuales (+2,4 pp). */
export const pp = (v: number | null | undefined, dec = 1) =>
  v == null ? t("N/D") : `${v > 0 ? "+" : ""}${nf(dec).format(v * 100)} pp`;
