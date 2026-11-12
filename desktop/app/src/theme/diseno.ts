/**
 * Modelo de diseno: TODO lo visual de la app es un objeto `Diseno` (colores,
 * vidrio, fondo, forma, tipografia, densidad, navegacion y gesto). Los temas
 * de fabrica viven aca; los personalizados se guardan en
 * config/diseno_escritorio.json via el backend. `aplicarDiseno` traduce el
 * objeto a variables CSS sobre :root y atributos data-* que usa app.css.
 */

export type Familia = "inter" | "geist" | "archivo" | "barlow";
export type Navegacion = "lateral" | "flotante" | "superior";
export type Gesto = "ninguno" | "reflejo" | "cifras" | "teclas";
export type TipoFondo = "solido" | "malla" | "mica" | "acrilico";
export type Densidad = "compacta" | "normal" | "amplia";
export type Sombra = "ninguna" | "suave" | "flotante";

export interface Colores {
  bg: string;
  surface: string;
  surface2: string;
  border: string;
  borderStrong: string;
  text: string;
  muted: string;
  faint: string;
  accent: string;
  accent2: string;
  accentContrast: string;
  pos: string;
  neg: string;
  warn: string;
  catCore: string;
  catSat: string;
  catOtra: string;
  catMuted: string;
  grid: string;
  tooltip: string;
  lineaValor: string;
  lineaCapital: string;
  chart: string[];
  bench: string[];
  displayBg: string;
  displayFg: string;
  /** Vidrio claro de la capa de navegacion y controles (los paneles de contenido usan `surface`). */
  vidrio: string;
}

export interface Diseno {
  id: string;
  nombre: string;
  descripcion: string;
  base: "oscuro" | "claro";
  colores: Colores;
  vidrio: { activo: boolean; blur: number; saturacion: number; brillo: number; refraccion: boolean };
  fondo: { tipo: TipoFondo; malla: string[]; animado: boolean; segunElDia: boolean };
  forma: { radioCard: number; radioCtrl: number; borde: number; sombra: Sombra };
  tipografia: { cuerpo: Familia; numeros: Familia; titulos: Familia; pesoTitulo: number; tamKpi: number; mayusculas: boolean };
  densidad: Densidad;
  navegacion: Navegacion;
  gesto: Gesto;
  /** true = tema de fabrica (no se puede pisar; editarlo crea una copia). */
  fabrica?: boolean;
}

export const FAMILIAS: Record<Familia, { nombre: string; css: string }> = {
  inter: { nombre: "Inter", css: '"Inter Variable", "Segoe UI Variable", system-ui, sans-serif' },
  geist: { nombre: "Geist", css: '"Geist Variable", "Segoe UI Variable", system-ui, sans-serif' },
  archivo: { nombre: "Archivo", css: '"Archivo Variable", "Segoe UI Variable", system-ui, sans-serif' },
  barlow: { nombre: "Barlow Condensed", css: '"Barlow Condensed", "Arial Narrow", system-ui, sans-serif' },
};

const DENSIDADES: Record<Densidad, { gap: string; padCard: string; padPage: string; sidebar: string; fila: string }> = {
  compacta: { gap: "12px", padCard: "14px 16px", padPage: "20px 26px 36px", sidebar: "200px", fila: "7px" },
  normal: { gap: "18px", padCard: "18px 20px", padPage: "28px 36px 48px", sidebar: "220px", fila: "9px" },
  amplia: { gap: "24px", padCard: "24px 26px", padPage: "36px 44px 56px", sidebar: "236px", fila: "11px" },
};

// ------------------------------------------------------------------ temas de fabrica
const vidrioNoche: Diseno = {
  id: "vidrio-noche",
  nombre: "Vidrio · noche",
  descripcion: "Liquid Glass oscuro: paneles de vidrio sobre un fondo de color que toma el tono del día.",
  base: "oscuro",
  fabrica: true,
  colores: {
    bg: "#05070d",
    surface: "rgba(20, 23, 33, 0.72)",
    surface2: "rgba(255, 255, 255, 0.07)",
    border: "rgba(255, 255, 255, 0.13)",
    borderStrong: "rgba(255, 255, 255, 0.24)",
    text: "#f5f7fb",
    muted: "#b6bdcc",
    faint: "#a3abbd",
    accent: "#4da3ff",
    accent2: "#5ee0c5",
    accentContrast: "#04101f",
    pos: "#30d158",
    neg: "#ff6259",
    warn: "#ffb340",
    catCore: "#64d2ff",
    catSat: "#30d158",
    catOtra: "#c98bff",
    catMuted: "#a1a1aa",
    grid: "rgba(255, 255, 255, 0.07)",
    tooltip: "rgba(24, 27, 36, 0.94)",
    lineaValor: "#4da3ff",
    lineaCapital: "#a1a1aa",
    chart: ["#0a84ff", "#30d158", "#ff9f0a", "#bf5af2", "#ff375f", "#64d2ff", "#ffd60a", "#ac8e68"],
    bench: ["#ffd60a", "#bf5af2", "#64d2ff", "#ff9f0a", "#ff375f"],
    displayBg: "rgba(0, 0, 0, 0.35)",
    displayFg: "#f5f7fb",
    vidrio: "rgba(255, 255, 255, 0.08)",
  },
  vidrio: { activo: true, blur: 28, saturacion: 180, brillo: 0.32, refraccion: true },
  fondo: { tipo: "malla", malla: ["#1d3bb8", "#6a2fd6", "#0b8f86", "#c2552c"], animado: true, segunElDia: true },
  forma: { radioCard: 22, radioCtrl: 12, borde: 1, sombra: "flotante" },
  tipografia: { cuerpo: "inter", numeros: "inter", titulos: "inter", pesoTitulo: 650, tamKpi: 28, mayusculas: false },
  densidad: "normal",
  navegacion: "flotante",
  gesto: "reflejo",
};

const vidrioDia: Diseno = {
  ...vidrioNoche,
  id: "vidrio-dia",
  nombre: "Vidrio · día",
  descripcion: "Liquid Glass claro: vidrio esmerilado blanco sobre colores pastel, como macOS.",
  base: "claro",
  colores: {
    bg: "#eef1f7",
    surface: "rgba(255, 255, 255, 0.78)",
    surface2: "rgba(15, 23, 42, 0.05)",
    border: "rgba(255, 255, 255, 0.75)",
    borderStrong: "rgba(15, 23, 42, 0.16)",
    text: "#0b1220",
    muted: "#465063",
    faint: "#555e74",
    accent: "#0071e3",
    accent2: "#00a3a3",
    accentContrast: "#ffffff",
    pos: "#17803d",
    neg: "#d12a20",
    warn: "#b26a00",
    catCore: "#0071e3",
    catSat: "#17803d",
    catOtra: "#8e44ec",
    catMuted: "#7b7f8a",
    grid: "rgba(15, 23, 42, 0.07)",
    tooltip: "rgba(255, 255, 255, 0.95)",
    lineaValor: "#0071e3",
    lineaCapital: "#8a909c",
    chart: ["#0071e3", "#17803d", "#e07c00", "#8e44ec", "#e5397f", "#0aa2c0", "#b89200", "#8d7b68"],
    bench: ["#e07c00", "#8e44ec", "#0aa2c0", "#e5397f", "#b89200"],
    displayBg: "rgba(255, 255, 255, 0.5)",
    displayFg: "#0b1220",
    vidrio: "rgba(255, 255, 255, 0.42)",
  },
  vidrio: { activo: true, blur: 30, saturacion: 170, brillo: 0.9, refraccion: true },
  fondo: { tipo: "malla", malla: ["#4f8cff", "#ff7eb6", "#3fd1b0", "#ffb347"], animado: true, segunElDia: true },
};

const anden: Diseno = {
  id: "anden",
  nombre: "Andén",
  descripcion: "Cartel de estación: negro mate, cifras blancas condensadas que cambian dígito a dígito.",
  base: "oscuro",
  fabrica: true,
  colores: {
    bg: "#09090a",
    surface: "#111113",
    surface2: "#1a1a1d",
    border: "#26262a",
    borderStrong: "#3a3a40",
    text: "#f3f2ec",
    muted: "#aeada5",
    faint: "#77766f",
    accent: "#ffb000",
    accent2: "#f3f2ec",
    accentContrast: "#121212",
    pos: "#8fcf96",
    neg: "#d9574d",
    warn: "#ffb000",
    catCore: "#f3f2ec",
    catSat: "#ffb000",
    catOtra: "#d6cfb8",
    catMuted: "#8a8983",
    grid: "#1c1c1f",
    tooltip: "rgba(18, 18, 20, 0.97)",
    lineaValor: "#ffb000",
    lineaCapital: "#8a8983",
    chart: ["#f3f2ec", "#ffb000", "#b8b7b0", "#c98a00", "#7d7c76", "#e3dcc6", "#5c5b56", "#ffd27a"],
    bench: ["#f3f2ec", "#ffd27a", "#b8b7b0", "#c98a00", "#7d7c76"],
    displayBg: "#202023",
    displayFg: "#f3f2ec",
    vidrio: "#111113",
  },
  vidrio: { activo: false, blur: 0, saturacion: 100, brillo: 0, refraccion: false },
  fondo: { tipo: "solido", malla: ["#1a1a1c", "#141416", "#202024", "#101012"], animado: false, segunElDia: false },
  forma: { radioCard: 4, radioCtrl: 3, borde: 1, sombra: "ninguna" },
  tipografia: { cuerpo: "inter", numeros: "barlow", titulos: "barlow", pesoTitulo: 600, tamKpi: 36, mayusculas: true },
  densidad: "compacta",
  navegacion: "lateral",
  gesto: "cifras",
};

const calculadora: Diseno = {
  id: "calculadora",
  nombre: "Calculadora",
  descripcion: "Diseño industrial Braun / Dieter Rams: gris cálido, teclas oscuras y un solo naranja.",
  base: "claro",
  fabrica: true,
  colores: {
    bg: "#d8d4cc",
    surface: "#ece9e3",
    surface2: "#e1ddd5",
    border: "#cdc7bc",
    borderStrong: "#b4ad9f",
    text: "#1d1c1a",
    muted: "#57534c",
    faint: "#7d786f",
    accent: "#e2560b",
    accent2: "#2b2a28",
    accentContrast: "#ffffff",
    pos: "#2c7a3a",
    neg: "#bf3426",
    warn: "#a8660f",
    catCore: "#2b2a28",
    catSat: "#5f8466",
    catOtra: "#4f6489",
    catMuted: "#857f75",
    grid: "#d6d1c8",
    tooltip: "rgba(43, 42, 40, 0.96)",
    lineaValor: "#2b2a28",
    lineaCapital: "#857f75",
    chart: ["#2b2a28", "#6b8f71", "#4f6489", "#c9a227", "#a35d3d", "#8f897e", "#3e7c8c", "#5c5a55"],
    bench: ["#2b2a28", "#4f6489", "#6b8f71", "#c9a227", "#a35d3d"],
    displayBg: "#262522",
    displayFg: "#f2eee5",
    vidrio: "#ece9e3",
  },
  vidrio: { activo: false, blur: 0, saturacion: 100, brillo: 0, refraccion: false },
  fondo: { tipo: "solido", malla: ["#d8d4cc", "#cfcac1", "#e2ded6", "#d4cfc6"], animado: false, segunElDia: false },
  forma: { radioCard: 18, radioCtrl: 10, borde: 1, sombra: "suave" },
  tipografia: { cuerpo: "archivo", numeros: "archivo", titulos: "archivo", pesoTitulo: 650, tamKpi: 28, mayusculas: false },
  densidad: "amplia",
  navegacion: "superior",
  gesto: "teclas",
};

const grafito: Diseno = {
  id: "grafito",
  nombre: "Grafito",
  descripcion: "El oscuro sobrio actual, como punto de comparación.",
  base: "oscuro",
  fabrica: true,
  colores: {
    bg: "#0b0c0e",
    surface: "#131417",
    surface2: "#1a1c20",
    border: "#24262b",
    borderStrong: "#363940",
    text: "#edeef0",
    muted: "#9a9ea7",
    faint: "#6c707a",
    accent: "#5b8def",
    accent2: "#46b3a4",
    accentContrast: "#ffffff",
    pos: "#3fb27f",
    neg: "#e5484d",
    warn: "#e2a336",
    catCore: "#7ea6f4",
    catSat: "#5cc49a",
    catOtra: "#b39dfa",
    catMuted: "#8b8f98",
    grid: "#1f2126",
    tooltip: "rgba(26, 28, 32, 0.97)",
    lineaValor: "#5b8def",
    lineaCapital: "#8b8f98",
    chart: ["#5b8def", "#46b3a4", "#d9a441", "#9b8afb", "#e07a5f", "#6cb85c", "#c77dba", "#7a8fa6"],
    bench: ["#d9a441", "#9b8afb", "#46b3a4", "#e07a5f", "#c77dba"],
    displayBg: "#0e0f12",
    displayFg: "#edeef0",
    vidrio: "#131417",
  },
  vidrio: { activo: false, blur: 0, saturacion: 100, brillo: 0, refraccion: false },
  fondo: { tipo: "solido", malla: ["#0b0c0e", "#101114", "#0d0e10", "#121316"], animado: false, segunElDia: false },
  forma: { radioCard: 10, radioCtrl: 8, borde: 1, sombra: "ninguna" },
  tipografia: { cuerpo: "inter", numeros: "inter", titulos: "inter", pesoTitulo: 600, tamKpi: 26, mayusculas: false },
  densidad: "normal",
  navegacion: "lateral",
  gesto: "ninguno",
};

export const FABRICA: Diseno[] = [vidrioNoche, vidrioDia, anden, calculadora, grafito];
export const DISENO_INICIAL = "vidrio-noche";

// ------------------------------------------------------------------ colores
/** Parsea #rgb, #rrggbb, rgb() o rgba() a [r, g, b, a]. */
export function parseColor(c: string): [number, number, number, number] {
  const s = c.trim();
  if (s.startsWith("#")) {
    let h = s.slice(1);
    if (h.length === 3) h = h.split("").map((x) => x + x).join("");
    const n = parseInt(h.slice(0, 6), 16);
    const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, a];
  }
  const m = s.match(/rgba?\(([^)]+)\)/i);
  if (m) {
    const p = m[1].split(",").map((x) => parseFloat(x));
    return [p[0] ?? 0, p[1] ?? 0, p[2] ?? 0, p[3] ?? 1];
  }
  return [0, 0, 0, 1];
}

export const rgba = ([r, g, b]: [number, number, number, number], a: number) => `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${+a.toFixed(3)})`;

export const aHex = (c: string) => {
  const [r, g, b] = parseColor(c);
  return `#${[r, g, b].map((x) => Math.round(x).toString(16).padStart(2, "0")).join("")}`;
};

/** Mismo color con otra transparencia (sirve para hex y rgba). */
export const conAlfa = (c: string, a: number) => rgba(parseColor(c), a);

// ------------------------------------------------------------------ aplicar
export function aplicarDiseno(d: Diseno, root: HTMLElement = document.documentElement) {
  const c = d.colores;
  const v: Record<string, string> = {
    "--bg": c.bg,
    "--surface": c.surface,
    "--surface-2": c.surface2,
    "--border": c.border,
    "--border-strong": c.borderStrong,
    "--text": c.text,
    "--muted": c.muted,
    "--faint": c.faint,
    "--accent": c.accent,
    "--accent-2": c.accent2,
    "--accent-contrast": c.accentContrast,
    "--pos": c.pos,
    "--neg": c.neg,
    "--warn": c.warn,
    "--cat-core": c.catCore,
    "--cat-sat": c.catSat,
    "--cat-otra": c.catOtra,
    "--cat-muted": c.catMuted,
    "--chart-grid": c.grid,
    "--tooltip-bg": c.tooltip,
    "--line-valor": c.lineaValor,
    "--line-capital": c.lineaCapital,
    "--display-bg": c.displayBg,
    "--display-fg": c.displayFg,
    "--glass": c.vidrio ?? c.surface,
    "--radius-card": `${d.forma.radioCard}px`,
    "--radius-ctrl": `${d.forma.radioCtrl}px`,
    "--border-width": `${d.forma.borde}px`,
    "--glass-blur": `${d.vidrio.blur}px`,
    "--glass-sat": `${d.vidrio.saturacion}%`,
    "--glass-rim": String(d.vidrio.brillo),
    "--font-body": FAMILIAS[d.tipografia.cuerpo].css,
    "--font-num": FAMILIAS[d.tipografia.numeros].css,
    "--font-display": FAMILIAS[d.tipografia.titulos].css,
    "--weight-heading": String(d.tipografia.pesoTitulo),
    "--fs-kpi": `${d.tipografia.tamKpi}px`,
    "--label-transform": d.tipografia.mayusculas ? "uppercase" : "none",
    "--label-tracking": d.tipografia.mayusculas ? "0.06em" : "0",
  };
  c.chart.forEach((x, i) => (v[`--chart-${i + 1}`] = x));
  c.bench.forEach((x, i) => (v[`--bench-${i + 1}`] = x));
  const den = DENSIDADES[d.densidad];
  Object.assign(v, { "--gap": den.gap, "--pad-card": den.padCard, "--pad-page": den.padPage, "--sidebar-w": den.sidebar, "--fila-pad": den.fila });

  const tinta = d.base === "oscuro" ? "0, 0, 0" : "30, 34, 48";
  v["--shadow-card"] =
    d.forma.sombra === "ninguna"
      ? "none"
      : d.forma.sombra === "suave"
        ? `0 1px 2px rgba(${tinta}, 0.06), 0 6px 16px -6px rgba(${tinta}, 0.16)`
        : `0 1px 1px rgba(${tinta}, 0.08), 0 18px 40px -16px rgba(${tinta}, ${d.base === "oscuro" ? 0.55 : 0.22})`;

  for (const [k, val] of Object.entries(v)) root.style.setProperty(k, val);
  root.dataset.base = d.base;
  root.dataset.nav = d.navegacion;
  root.dataset.gesto = d.gesto;
  root.dataset.vidrio = d.vidrio.activo ? "on" : "off";
  root.dataset.refraccion = d.vidrio.activo && d.vidrio.refraccion ? "on" : "off";
  root.dataset.fondo = d.fondo.tipo;
  root.dataset.densidad = d.densidad;
  root.style.colorScheme = d.base === "oscuro" ? "dark" : "light";
}

/** Copia profunda (los temas se editan sobre una copia). */
export const clonar = (d: Diseno): Diseno => JSON.parse(JSON.stringify(d));
