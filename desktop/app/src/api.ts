// Cliente de la API local (desktop/backend/server.py).
export const API = "http://127.0.0.1:8765/api";

export type Fila = Record<string, string | number | null>;

export interface Panel {
  ccl: number | null;
  actualizado: string;
  avisos: string[];
  kpis: {
    valor_ars: number;
    valor_usd: number | null;
    pnl_pct: number | null;
    brecha_pct: number | null;
    brecha_fecha: string | null;
    variacion: {
      ars: number | null;
      pct: number | null;
      fecha: string | null;
      suben: { ticker: string; pct: number }[];
      bajan: { ticker: string; pct: number }[];
    };
  };
  meta: { usd: number; fecha: string | null; pct: number; falta: number } | null;
  orden_tickers: string[];
  objetivo: { ticker: string; pct: number | null }[];
  tenencia: Fila[];
  comision_pct: number;
  banda_default: number;
}

export interface Curva {
  fechas: string[];
  valor: (number | null)[];
  capital: (number | null)[];
  benchmarks: Record<string, (number | null)[]>;
  advertencias: string[];
}

export interface Rebalanceo {
  monto: number;
  asignado: number;
  comision: number;
  costo_total: number;
  vuelto: number;
  advertencias: string[];
  ordenes: Fila[];
  proyeccion: Record<string, number | null>;
}

export interface Banda {
  banda: number;
  monto_nuevo: number;
  venta_bruta: number;
  comision_venta: number;
  venta_neta: number;
  efectivo_disponible: number;
  compra_neta: number;
  comision_compra: number;
  costo_compra: number;
  efectivo_sobrante: number;
  advertencias: string[];
  desviaciones: Fila[];
  ventas: Fila[];
  compras: Fila[];
}

export async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${ruta}`, init);
  if (!r.ok) {
    const cuerpo = await r.json().catch(() => ({}));
    throw new Error(cuerpo.detail ?? `Error ${r.status}`);
  }
  return r.json();
}

/** Espera a que el backend Python termine de arrancar (lo lanza Tauri). */
export async function esperarBackend(timeoutMs = 60000): Promise<void> {
  const fin = Date.now() + timeoutMs;
  while (Date.now() < fin) {
    try {
      await pedir("/health");
      return;
    } catch {
      await new Promise((ok) => setTimeout(ok, 400));
    }
  }
  throw new Error("No se pudo conectar con el motor de datos (backend Python).");
}

export const getPanel = () => pedir<Panel>("/panel");
export const getCurva = () => pedir<Curva>("/curva");
export const refrescar = () => pedir("/refresh", { method: "POST" });

export interface DatosUsuario {
  raiz: string;
  movimientos: string;
  csv: number;
  demo: boolean;
}
export const getDatosUsuario = () => pedir<DatosUsuario>("/datos");
export const abrirCarpeta = () => pedir("/abrir-carpeta", { method: "POST" });
export const postRebalanceo = (monto: number) =>
  pedir<Rebalanceo>("/rebalanceo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ monto }),
  });

export const postBanda = (banda: number, monto_nuevo: number) =>
  pedir<Banda>("/banda", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ banda, monto_nuevo }),
  });

// ---------------------------------------------------------------- Configuracion
export interface CategoriaCfg {
  nombre: string;
  objetivo: number | null;
  descripcion: string;
}

export interface ActivoCfg {
  ticker: string;
  nombre: string;
  categoria: string;
  tipo: string;
  objetivo_cat: number | null;
  ticker_mercado: string;
  alias: string;
}

export interface ManualCfg {
  ticker: string;
  cantidad: number | null;
  categoria: string;
}

export interface Config {
  categorias: CategoriaCfg[];
  activos: ActivoCfg[];
  tipos: string[];
  tolerancia: number;
  ultima_actualizacion: string | null;
  manuales: ManualCfg[];
  error_manuales: string | null;
  categoria_fuera: string;
}

const json = (metodo: string, cuerpo: unknown): RequestInit => ({
  method: metodo,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cuerpo),
});

export const getConfig = () => pedir<Config>("/config");
export const validarConfig = (c: { categorias: CategoriaCfg[]; activos: ActivoCfg[] }) =>
  pedir<{ errores: string[] }>("/config/validar", json("POST", c));
export const guardarConfig = (c: { categorias: CategoriaCfg[]; activos: ActivoCfg[] }) => pedir("/config", json("PUT", c));
export const guardarManuales = (lista: ManualCfg[]) => pedir("/manuales", json("PUT", lista));

// ---------------------------------------------------------------- Rendimiento
export type UnidadId = "usd" | "ars" | "real";
export interface SerieT {
  fechas: string[];
  valores: (number | null)[];
}
export interface ResumenRend {
  unidad: UnidadId;
  nombre: string;
  ganancia: number | null;
  aportado: number | null;
  ganancia_pct: number | null;
  twr_total: number | null;
  twr_anual: number | null;
  tir_anual: number | null;
  extrapolacion: boolean;
  fecha_inicio: string;
  dias: number;
}
export interface Rendimiento {
  unidad: UnidadId;
  unidades: { id: UnidadId; nombre: string }[];
  nota_unidad: string;
  avisos: string[];
  resumen: ResumenRend;
  resumenes: ResumenRend[];
  acumulado: { cartera: SerieT; benchmarks: Record<string, SerieT>; referencias: Record<string, SerieT> };
  vs_indice: { label: string; exceso_6m: number | null; exceso_12m: number | null; exceso_total: number | null; pct_ventanas: number | null; serie_6m: SerieT | null }[];
  mensual: { anios: number[]; meses: string[]; valores: (number | null)[][]; anual: (number | null)[] } | null;
  categorias: { nombre: string; otros: boolean; desde: string; twr: number | null; twr_anual: number | null; ganancia: number | null; peso: number | null; serie: SerieT }[];
}
export interface Contribucion {
  periodo: string;
  unidad: UnidadId;
  total: number | null;
  filas: { ticker: string; valor_inicial: number | null; flujo: number | null; valor_final: number | null; contribucion: number | null; estado: string; pct_resultado: number | null }[];
}
export interface TirCuenta {
  en_usd: boolean;
  tir_cuenta: number | null;
  tir_acciones: number | null;
  diferencia: number | null;
  ganancia: number | null;
  acciones_ars: number;
  otros_ars: number;
  flujos: number;
}

export const getRendimiento = (unidad: UnidadId) => pedir<Rendimiento>(`/rendimiento?unidad=${unidad}`);
export const getContribucion = (unidad: UnidadId, periodo: string) =>
  pedir<Contribucion>(`/rendimiento/contribucion?unidad=${unidad}&periodo=${periodo}`);
export const getTirCuenta = (otros?: number) => pedir<TirCuenta>(`/rendimiento/tir_cuenta${otros != null ? `?otros=${otros}` : ""}`);
export const guardarOtrosCuenta = (valor: number) => pedir("/metas/otros_cuenta", json("PUT", { valor }));

// ---------------------------------------------------------------- Riesgo
export interface RiesgoReal {
  en_usd: boolean;
  rf: number;
  metricas: {
    error?: string;
    volatilidad: number | null;
    sharpe: number | null;
    sortino: number | null;
    beta: number | null;
    correlacion: number | null;
    retorno_anual: number | null;
    ruedas: number;
    vol_1m: SerieT;
    vol_3m: SerieT;
  };
  drawdown: {
    max: number | null;
    fecha_pico: string | null;
    fecha_valle: string | null;
    fecha_recuperacion: string | null;
    dias_caida: number;
    dias_recuperacion: number | null;
    actual: number | null;
    serie: SerieT;
  };
}
export interface Stress {
  mensaje?: string;
  valor_usd?: number | null;
  escenarios: {
    nombre: string;
    hoy: number | null;
    hoy_supuesto: boolean;
    objetivo: number | null;
    objetivo_supuesto: boolean;
    perdida_usd: number | null;
    detalle: { ticker: string; aporte: number | null; retorno: number | null; peso: number | null; fuente: string }[];
  }[];
}
export interface Barra {
  nombre: string;
  pct: number | null;
}
export interface Composicion {
  concentracion: { error?: string; top1_ticker: string; top1: number; top3: number; top5: number; n_efectivo: number; n: number; sector: Barra[]; pais: Barra[]; moneda: Barra[] };
  riesgo: { error?: string; filas: { ticker: string; peso: number | null; riesgo: number | null; ratio: number | null }[]; sin_datos: string[]; excluidos: string[] };
  exposicion: {
    empresas: { empresa: string; directo: number | null; via_etfs: number | null; total: number | null; detalle: string }[];
    superpuestas: string[];
    btc: { capital: number | null; riesgo: number | null; filas: { ticker: string; peso: number | null; que_es: string }[] } | null;
  } | null;
}
export interface Objetivo {
  volatilidad: number | null;
  max_drawdown: number | null;
  advertencias: string[];
  sin_datos: string[];
  correlacion: { tickers: string[]; valores: (number | null)[][] };
  por_activo: { ticker: string; volatilidad: number | null; max_drawdown: number | null }[];
}
export const getRiesgoReal = (rf?: number) => pedir<RiesgoReal>(`/riesgo/real${rf != null ? `?rf=${rf}` : ""}`);
export const getStress = () => pedir<Stress>("/riesgo/stress");
export const getComposicion = () => pedir<Composicion>("/riesgo/composicion");
export const getObjetivo = () => pedir<Objetivo>("/riesgo/objetivo");

// ---------------------------------------------------------------- Aportes y dividendos
export interface Aportes {
  aportes: {
    error?: string;
    en_usd: boolean;
    neto: number | null;
    neto_usd: number | null;
    depositado: number | null;
    retirado: number | null;
    promedio_6m: number | null;
    promedio_6m_usd: number | null;
    racha: number;
    meses_con_aporte: number;
    meses_totales: number;
    mensual: { mes: string; depositos: number | null; retiros: number | null; neto: number | null; neto_usd: number | null; acumulado: number | null; acumulado_usd: number | null }[];
  };
  dividendos: {
    error?: string;
    ultimos_12m_ars: number | null;
    ultimos_12m_usd: number | null;
    total_ars: number | null;
    total_usd: number | null;
    rendimiento: number | null;
    meses: string[];
    por_tipo: Record<string, (number | null)[]>;
    tiene_renta: boolean;
    en_especie: { ticker: string; nominales: number | null }[];
  };
  tickers_operados: string[];
}
export interface Compras {
  ticker: string;
  unidad: "ars" | "usd";
  precio: SerieT;
  operaciones: { fecha: string; tipo: string; cantidad: number | null; precio: number | null }[];
  timing: {
    promedio_compra: number | null;
    promedio_periodo: number | null;
    referencia_dca: number | null;
    ventaja_pct: number | null;
    bajo_precio_actual: number | null;
    precio_actual: number | null;
    n_compras: number;
    n_ventas: number;
  } | null;
}
export const getAportes = () => pedir<Aportes>("/aportes");
export const getCompras = (ticker: string, unidad: "ars" | "usd") => pedir<Compras>(`/aportes/compras?ticker=${encodeURIComponent(ticker)}&unidad=${unidad}`);

// ---------------------------------------------------------------- Metas
export interface Metas {
  valor_usd: number | null;
  meta_usd: number | null;
  fecha_objetivo: string | null;
  aporte_mensual_usd: number | null;
  escenario: string | null;
  horizonte_anios: number | null;
  escenarios: Record<string, number>;
  defaults: { aporte_real: number | null; vol_real: number | null; vol_hist: number | null; twr_real: number | null };
}
export interface Proyeccion {
  fechas: string[];
  p10: (number | null)[];
  p25: (number | null)[];
  p50: (number | null)[];
  p75: (number | null)[];
  p90: (number | null)[];
  aportado: SerieT;
  final_p50: number | null;
  final_p10: number | null;
  final_p90: number | null;
  aportado_extra: number | null;
  prob_meta: number | null;
  mes_meta: string | null;
  prob_meta_en_fecha: number | null;
}
export interface ParamsProyeccion {
  aporte: number;
  escenario: string;
  volatilidad: number;
  anios: number;
}
export const getMetas = () => pedir<Metas>("/metas");
export const guardarMeta = (meta_usd: number | null, fecha_objetivo: string | null) => pedir("/metas/meta", json("PUT", { meta_usd, fecha_objetivo }));
export const postProyeccion = (p: ParamsProyeccion) => pedir<Proyeccion>("/metas/proyeccion", json("POST", p));
export const guardarParametros = (p: ParamsProyeccion) => pedir("/metas/parametros", json("PUT", p));

// ---------------------------------------------------------------- Transicion y diario
export interface Transicion {
  ventas_neto: number;
  ventas_neto_usd: number | null;
  para_reinvertir: number | null;
  comisiones: number | null;
  comisiones_usd: number | null;
  vuelto: number | null;
  ventas: { ticker: string; motivo: string; nominales: number | null; precio: number | null; neto: number | null; usd: number | null }[];
  compras: { ticker: string; nominales: number | null; precio: number | null; costo: number | null; usd: number | null }[];
  categorias: { nombre: string; antes: number | null; despues: number | null; objetivo: number | null }[];
  stress: { nombre: string; hoy: number | null; despues: number | null; objetivo: number | null }[] | { error: string } | null;
  advertencias: string[];
}
export interface Diario {
  referencia?: string;
  entradas: { id: string; fecha: string; ticker: string; accion: string; motivo: string; dias: number; activo_usd: number | null; ref_usd: number | null; diferencia: number | null; resultado: string; revisar: boolean }[];
  total: number;
  evaluables: number;
  aciertos: number | null;
  revisar: number;
  acciones: string[];
  opciones: string[];
}
export const getOpcionesTransicion = () => pedir<{ tickers: string[]; fuera: string[] }>("/transicion/opciones");
export const postTransicion = (vender: string[], monto: number, sobreponderados: boolean) => pedir<Transicion>("/transicion", json("POST", { vender, monto, sobreponderados }));
export const getDiario = () => pedir<Diario>("/diario");
export const postDecision = (d: { ticker: string; accion: string; motivo: string; horizonte_meses: number }) => pedir("/diario", json("POST", d));
export const borrarDecision = (id: string) => pedir(`/diario/${encodeURIComponent(id)}`, { method: "DELETE" });

// ---------------------------------------------------------------- Diseno
export const getDiseno = () => pedir<{ activo: string | null; personalizados: unknown[] }>("/diseno");
export const guardarDiseno = (activo: string, personalizados: unknown[]) => pedir("/diseno", json("PUT", { activo, personalizados }));
