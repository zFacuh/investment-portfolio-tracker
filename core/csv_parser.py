"""
core/csv_parser.py

Modulo de Ingesta: parsea los archivos de movimientos exportados por
Cocos Capital (formato "nroTicket;nroComprobante;fechaEjecucion;...")
y devuelve un DataFrame limpio y tipado, listo para ser consumido por
el resto de la aplicacion (calculo de tenencia actual, historico, etc.).

Particularidades del export de Cocos Capital que este parser resuelve:

- Separador de campos: ';'.
- Formato numerico argentino: '.' como separador de miles y ',' como
  separador decimal (ej: "1.234,56" -> 1234.56, "-40.000" -> -40000.0).
- Fechas en formato DD-MM-YYYY.
- La columna 'instrumento' trae el nombre largo del activo seguido del
  ticker entre parentesis al final, a veces duplicado
  (ej: "CEDEAR RIGETTI COMPUTING (RGTI) (RGTI)" -> ticker = "RGTI").
  Los movimientos de cash puro (Recibo De Cobro, Orden De Pago, etc.)
  no tienen 'instrumento', por lo que 'ticker' queda como NaN.
- Los bonos (renta fija, ej. AL30) cotizan "cada 100 nominales": para
  esos instrumentos montoBruto = cantidad * precio / 100, en vez de
  cantidad * precio como en acciones/CEDEARs. Este parser NO recalcula
  montos, solo limpia y tipa los datos tal cual vienen del broker; esa
  logica de dominio se resuelve en el modulo de tenencia/valuacion.

Housekeeping automatico de archivos (v5.0):
  Cada vez que se descarga un export nuevo de Cocos Capital a mano en
  `data/movimientos/` (o el directorio configurado), la carpeta se va
  llenando de .csv viejos. `parsear_movimientos()` ahora arranca
  archivando automaticamente todos los .csv "sueltos" salvo el mas
  reciente (por fecha de modificacion) en una subcarpeta `procesados/`
  DENTRO del mismo directorio -- NO los borra fisicamente. La carpeta
  principal siempre muestra un unico archivo (el ultimo que bajaste),
  pero el parser sigue leyendo y consolidando TODOS los .csv, incluidos
  los ya archivados en `procesados/`, exactamente como hacia antes con
  multiples archivos sueltos.

  Por que archivar y no borrar (os.remove): los exports de Cocos Capital
  son PARCIALES -- cada uno trae los movimientos de un periodo, no el
  historial completo de la cuenta -- por eso el parser ya dedupeaba por
  'nroTicket' "por si dos exports se solapan". Si se borraran
  fisicamente los archivos viejos, la proxima vez que corras esta
  funcion esos movimientos historicos desaparecerian PARA SIEMPRE (el
  parser solo puede leer lo que sigue existiendo en disco). Archivar
  logra la misma carpeta "limpia" sin ese riesgo. Ver
  `archivar_csvs_antiguos()` mas abajo para el detalle.

Uso:
    from core.csv_parser import parsear_movimientos
    df = parsear_movimientos()  # data/movimientos, o data/demo si esta vacia
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
from core.rutas import DEMO_DIR, MOVIMIENTOS_DIR  # noqa: E402

DEFAULT_DATA_DIR = MOVIMIENTOS_DIR
# Datos de demostracion (inventados) que se usan mientras data/movimientos/
# no tenga ningun .csv: asi la app se puede probar recien clonada.
DEMO_DATA_DIR = DEMO_DIR
NOMBRE_SUBCARPETA_PROCESADOS = "procesados"

PathLike = Union[str, Path]

COLUMNAS_NUMERICAS = [
    "cantidad",
    "precio",
    "montoBruto",
    "comision",
    "ddmm",
    "iva",
    "otros",
    "total",
]
COLUMNAS_FECHA = ["fechaEjecucion", "fechaLiquidacion"]

COLUMNAS_ESPERADAS = [
    "nroTicket",
    "nroComprobante",
    "fechaEjecucion",
    "fechaLiquidacion",
    "tipoOperacion",
    "instrumento",
    "moneda",
    "mercado",
    "cantidad",
    "precio",
    "montoBruto",
    "comision",
    "ddmm",
    "iva",
    "otros",
    "total",
]

# Mapeo de tipoOperacion "crudo" (tal cual lo exporta Cocos Capital) a una
# categoria normalizada, para que el resto de la app no tenga que lidiar
# con los strings exactos (y sus variantes de mayusculas) del broker.
MAPA_TIPO_OPERACION = {
    "Compra": "COMPRA",
    "Venta": "VENTA",
    "Liquidacion Suscripcion Fci": "FCI_SUSCRIPCION",
    "Liquidacion Rescate Fci": "FCI_RESCATE",
    "Recibo De Cobro": "INGRESO_CASH",
    "Orden De Pago": "EGRESO_CASH",
    "Dividendos": "DIVIDENDO",
    "Dividendos En Especie": "DIVIDENDO_ESPECIE",
    "Nota Debito Dividendos Ars": "AJUSTE_DIVIDENDO",
    "Nota Credito Dividendos Ars": "AJUSTE_DIVIDENDO",
    "Nota De Credito Conversion": "CONVERSION_MONEDA",
    "Renta Y Amortizacion Usd": "RENTA_AMORTIZACION",
}

_TICKER_RE = re.compile(r"\(([^()]+)\)\s*$")
_ENCODINGS_A_PROBAR = ("utf-8", "utf-8-sig", "latin1", "cp1252")


class CsvParserError(Exception):
    """Error al buscar, leer o parsear los CSV de movimientos."""


# ---------------------------------------------------------------------------
# Limpieza de valores individuales
# ---------------------------------------------------------------------------
def _parse_numero_ar(valor) -> Optional[float]:
    """
    Convierte un string en formato numerico argentino a float.

    "1.234,56" -> 1234.56
    "-40.000"  -> -40000.0
    "0,24"     -> 0.24
    ""/None    -> None
    """
    if valor is None:
        return None
    valor = str(valor).strip()
    if valor == "" or valor.lower() == "nan":
        return None
    valor = valor.replace(".", "").replace(",", ".")
    try:
        return float(valor)
    except ValueError:
        return None


def _extraer_ticker(instrumento: str) -> Optional[str]:
    """Extrae el ticker del ultimo grupo entre parentesis de 'instrumento'."""
    if not isinstance(instrumento, str) or not instrumento.strip():
        return None
    match = _TICKER_RE.search(instrumento.strip())
    return match.group(1).strip() if match else None


def _normalizar_tipo_operacion(tipo_operacion: str) -> str:
    """Normaliza variantes de capitalizacion antes de mapear (ej. la
    columna a veces viene toda en mayusculas para ciertos movimientos)."""
    if not isinstance(tipo_operacion, str):
        return "OTRO"
    clave = tipo_operacion.strip().title()
    return MAPA_TIPO_OPERACION.get(clave, "OTRO")


# ---------------------------------------------------------------------------
# Housekeeping automatico: archiva (NO borra) los .csv viejos
# ---------------------------------------------------------------------------
def _nombre_sin_colision(destino_dir: Path, nombre_archivo: str) -> Path:
    """
    Si `nombre_archivo` ya existe en `destino_dir` (ej. el mismo export se
    bajo dos veces con el mismo nombre de archivo), le agrega un sufijo de
    timestamp para no pisar/perder el que ya estaba archivado.
    """
    destino = destino_dir / nombre_archivo
    if not destino.exists():
        return destino
    stem, sufijo = Path(nombre_archivo).stem, Path(nombre_archivo).suffix
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    return destino_dir / f"{stem}_{marca}{sufijo}"


def archivar_csvs_antiguos(
    directorio: PathLike = DEFAULT_DATA_DIR,
    subcarpeta: str = NOMBRE_SUBCARPETA_PROCESADOS,
) -> Tuple[List[Path], List[str]]:
    """
    Si en `directorio` hay MAS DE UN .csv "suelto" (sin contar los que ya
    estan en `subcarpeta`), conserva a la vista solo el mas reciente (por
    fecha de modificacion, st_mtime) y MUEVE los demas a
    `directorio/<subcarpeta>/`.

    Seguridad: esta funcion NUNCA usa os.remove/unlink. Se decidio
    archivar en vez de borrar fisicamente porque los exports de Cocos
    Capital son parciales (no un historial acumulado completo cada vez):
    borrarlos perderia movimientos historicos para siempre. Moverlos a
    `procesados/` deja la carpeta principal igual de "limpia" (un solo
    archivo a la vista) sin ese riesgo -- `buscar_archivos_csv()` sigue
    leyendo esa subcarpeta para que el parseo no pierda nada.

    Devuelve (archivados, errores):
      - archivados: paths de destino de cada archivo que se pudo mover.
      - errores: un mensaje por archivo que NO se pudo mover (ej. porque
        esta bloqueado por Windows por seguir abierto en Excel/Cocos).
        Un fallo puntual nunca interrumpe el resto: se loguea con
        try/except y se sigue con los demas archivos.

    No lanza excepciones por errores de archivado individuales (a
    proposito: es housekeeping best-effort, nunca debe impedir que
    parsear_movimientos() siga funcionando con lo que haya).
    """
    directorio = Path(directorio)
    if not directorio.exists():
        return [], []

    # Solo los .csv directamente en `directorio` (glob, no rglob): los que
    # ya estan en procesados/ no vuelven a evaluarse para re-archivar.
    archivos = sorted(directorio.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(archivos) <= 1:
        return [], []  # 0 o 1 archivo: ya esta "limpio", nada que hacer.

    mas_reciente, *antiguos = archivos
    print(
        f"[csv_parser] Housekeeping: conservando '{mas_reciente.name}' (el mas reciente) "
        f"a la vista; archivando {len(antiguos)} export(s) anterior(es) en '{subcarpeta}/'."
    )

    destino_dir = directorio / subcarpeta
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        error = f"No se pudo crear la carpeta de archivado '{destino_dir}': {e}"
        print(f"[csv_parser] {error}")
        return [], [error]

    archivados: List[Path] = []
    errores: List[str] = []
    for archivo in antiguos:
        try:
            destino = _nombre_sin_colision(destino_dir, archivo.name)
            shutil.move(str(archivo), str(destino))
            archivados.append(destino)
            print(f"[csv_parser] Archivado: '{archivo.name}' -> '{subcarpeta}/{destino.name}'")
        except PermissionError as e:
            # Tipico en Windows: el archivo sigue abierto en Excel/Cocos
            # Capital, o el usuario/proceso no tiene permisos de escritura.
            msg = (
                f"No se pudo archivar '{archivo.name}' (permiso denegado -- "
                f"¿esta abierto en Excel u otro programa? cerralo e intenta de nuevo): {e}"
            )
            errores.append(msg)
            print(f"[csv_parser] {msg}")
        except OSError as e:
            msg = f"No se pudo archivar '{archivo.name}': {e}"
            errores.append(msg)
            print(f"[csv_parser] {msg}")

    return archivados, errores


# ---------------------------------------------------------------------------
# Lectura de archivos
# ---------------------------------------------------------------------------
def buscar_archivos_csv(directorio: PathLike = DEFAULT_DATA_DIR) -> List[Path]:
    """
    Devuelve la lista (ordenada) de .csv encontrados en `directorio`,
    INCLUYENDO los que ya fueron archivados en su subcarpeta 'procesados/'
    por `archivar_csvs_antiguos()`: el housekeeping automatico mueve
    archivos para mantener la carpeta principal ordenada, pero el parser
    igual tiene que leerlos a TODOS para no perder historial.
    """
    directorio = Path(directorio)
    if not directorio.exists():
        raise CsvParserError(f"No existe el directorio: {directorio}")
    archivos = sorted(directorio.rglob("*.csv"))
    if not archivos:
        raise CsvParserError(f"No se encontraron archivos .csv en: {directorio}")
    return archivos


def _leer_csv(path: Path) -> pd.DataFrame:
    """Lee un unico CSV de Cocos Capital, probando encodings comunes."""
    ultimo_error: Optional[Exception] = None
    for encoding in _ENCODINGS_A_PROBAR:
        try:
            df = pd.read_csv(path, sep=";", encoding=encoding, dtype=str)
            faltantes = set(COLUMNAS_ESPERADAS) - set(df.columns)
            if faltantes:
                raise CsvParserError(
                    f"'{path.name}' no tiene el formato esperado de Cocos "
                    f"Capital. Faltan columnas: {sorted(faltantes)}"
                )
            return df
        except UnicodeDecodeError as e:
            ultimo_error = e
            continue
    raise CsvParserError(
        f"No se pudo leer '{path.name}' con ningun encoding conocido "
        f"({', '.join(_ENCODINGS_A_PROBAR)})."
    ) from ultimo_error


# ---------------------------------------------------------------------------
# Punto de entrada principal
# ---------------------------------------------------------------------------
def directorio_movimientos() -> Path:
    """data/movimientos/ si tiene algun .csv (los tuyos); si no, data/demo/."""
    if DEFAULT_DATA_DIR.exists() and any(DEFAULT_DATA_DIR.rglob("*.csv")):
        return DEFAULT_DATA_DIR
    return DEMO_DATA_DIR


def usando_demo() -> bool:
    """True si la app esta mostrando los datos de demostracion."""
    return directorio_movimientos() == DEMO_DATA_DIR


def parsear_movimientos(directorio: Optional[PathLike] = None) -> pd.DataFrame:
    """
    Busca todos los .csv en `directorio`, los consolida en un unico
    DataFrame limpio con:

      - columnas numericas convertidas a float (formato AR -> float),
      - fechas convertidas a datetime,
      - columna 'ticker' derivada de 'instrumento',
      - columna 'tipo_operacion_norm' con el tipo de operacion normalizado,
      - duplicados eliminados (por 'nroTicket', por si dos exports se solapan),
      - orden cronologico ascendente.

    Antes de leer nada, corre el housekeeping automatico
    (archivar_csvs_antiguos): si hay mas de un .csv suelto en
    `directorio`, archiva los mas viejos en 'procesados/' (nunca los
    borra). Es best-effort -- si algo falla (ej. permisos en Windows) se
    loguea y se sigue igual con el parseo de todo lo que haya.

    Lanza CsvParserError si el directorio no existe, no tiene .csv, o
    algun archivo no respeta el formato esperado de Cocos Capital.
    """
    directorio = Path(directorio) if directorio is not None else directorio_movimientos()
    _archivados, errores_archivado = archivar_csvs_antiguos(directorio)
    for error in errores_archivado:
        print(f"[csv_parser] (housekeeping, no bloqueante) {error}")

    archivos = buscar_archivos_csv(directorio)

    dfs = []
    for archivo in archivos:
        df = _leer_csv(archivo)
        df["archivo_origen"] = archivo.name
        dfs.append(df)

    movimientos = pd.concat(dfs, ignore_index=True)

    # --- Tipado numerico (formato argentino) ---
    for columna in COLUMNAS_NUMERICAS:
        movimientos[columna] = movimientos[columna].apply(_parse_numero_ar)

    # --- Tipado de fechas ---
    for columna in COLUMNAS_FECHA:
        movimientos[columna] = pd.to_datetime(
            movimientos[columna], format="%d-%m-%Y", errors="coerce"
        )

    # --- Ticker derivado de instrumento ---
    movimientos["instrumento"] = movimientos["instrumento"].fillna("").str.strip()
    movimientos["ticker"] = movimientos["instrumento"].apply(_extraer_ticker)

    # --- Normalizacion de tipoOperacion ---
    movimientos["tipoOperacion"] = movimientos["tipoOperacion"].str.strip()
    movimientos["tipo_operacion_norm"] = movimientos["tipoOperacion"].apply(
        _normalizar_tipo_operacion
    )

    # --- Identificadores como enteros nullable (pueden venir vacios) ---
    for columna in ("nroTicket", "nroComprobante"):
        movimientos[columna] = pd.to_numeric(
            movimientos[columna], errors="coerce"
        ).astype("Int64")

    # --- Deduplicar por nroTicket (ej. si dos exports mensuales se solapan) ---
    antes = len(movimientos)
    movimientos = movimientos.drop_duplicates(subset=["nroTicket"], keep="first")
    duplicados_removidos = antes - len(movimientos)
    if duplicados_removidos:
        print(f"[csv_parser] {duplicados_removidos} movimiento(s) duplicado(s) descartado(s).")

    # --- Orden cronologico ---
    movimientos = movimientos.sort_values("fechaEjecucion").reset_index(drop=True)

    columnas_finales = [
        "nroTicket",
        "nroComprobante",
        "fechaEjecucion",
        "fechaLiquidacion",
        "tipoOperacion",
        "tipo_operacion_norm",
        "instrumento",
        "ticker",
        "moneda",
        "mercado",
        "cantidad",
        "precio",
        "montoBruto",
        "comision",
        "ddmm",
        "iva",
        "otros",
        "total",
        "archivo_origen",
    ]
    return movimientos[columnas_finales]


if __name__ == "__main__":
    df = parsear_movimientos()

    print(f"{len(df)} movimientos consolidados desde {df['archivo_origen'].nunique()} archivo(s).")
    print(f"Rango de fechas: {df['fechaEjecucion'].min().date()} -> {df['fechaEjecucion'].max().date()}")
    print(f"Tickers detectados: {sorted(t for t in df['ticker'].dropna().unique())}")
    print()
    print("Movimientos por tipo_operacion_norm:")
    print(df["tipo_operacion_norm"].value_counts().to_string())
    print()
    print("Primeras filas:")
    print(
        df[["fechaEjecucion", "tipoOperacion", "ticker", "cantidad", "precio", "total"]]
        .head(10)
        .to_string(index=False)
    )
