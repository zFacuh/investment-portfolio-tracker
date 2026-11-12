/**
 * Mensajes que arma el motor en Python (avisos, errores de validacion) y que
 * llevan datos adentro, asi que no se pueden buscar tal cual en el diccionario.
 * Cada patron tiene que cubrir el mensaje ENTERO (^...$). El reemplazo puede ser
 * un texto con $1, $2... o una funcion que recibe `tr` para traducir un pedazo
 * (ej. el detalle de un error que a su vez es otro mensaje conocido).
 */
type Tr = (s: string) => string;
export type Reemplazo = string | ((tr: Tr, ...g: string[]) => string);

export const PATRONES_EN: [RegExp, Reemplazo][] = [
  // ---------------------------------------------------------------- backend (server.py)
  [/^Dolar CCL no disponible \((.*)\)\. Los montos en USD no van a estar disponibles\.$/s, "CCL dollar unavailable ($1). Amounts in USD won't be available."],
  [/^Tenencias manuales no disponibles \((.*)\)\.$/s, "Manual holdings unavailable ($1)."],
  [/^Sin cotizacion en vivo: (.*)\.$/s, "No live quote for: $1."],
  [/^Curva historica no disponible: (.*)$/s, (tr, e) => `Historical curve unavailable: ${tr(e)}`],
  [/^(.*) Las vistas en dólares no van a estar disponibles\.$/s, (tr, e) => `${tr(e)} Dollar views won't be available.`],
  [/^(.*) Las vistas ajustadas por inflación no van a estar disponibles\.$/s, (tr, e) => `${tr(e)} Inflation-adjusted views won't be available.`],
  [/^Error de configuracion: (.*)$/s, (tr, e) => `Settings error: ${tr(e)}`],
  [/^Error leyendo los CSV de movimientos: (.*)$/s, "Error reading the transaction CSVs: $1"],
  [/^No se pudo reconstruir la curva histórica, que es la base de esta pestaña: (.*)$/s, (tr, e) => `Couldn't rebuild the historical curve, which this tab is based on: ${tr(e)}`],
  [/^No se pudo calcular la contribución: (.*)$/s, (tr, e) => `Couldn't calculate the contribution: ${tr(e)}`],
  [/^No se pudo correr el stress test: (.*)$/s, (tr, e) => `Couldn't run the stress test: ${tr(e)}`],
  [/^No se pudo calcular la analítica de riesgo: (.*)$/s, (tr, e) => `Couldn't calculate the risk analytics: ${tr(e)}`],
  [/^No hay precio histórico para (.*)\.$/s, "No price history for $1."],
  [/^Escenario desconocido: (.*)$/s, "Unknown scenario: $1"],
  [/^Error (\d+)$/, "Error $1"],
  [/^Otros \((\d+)\)$/, "Others ($1)"],
  [/^ETF · (.*)$/, "ETF · $1"],
  [/^supuesto: (.*)$/, "assumed: $1"],
  [/^Basado en (.*)\.$/, (tr, n) => `Based on ${tr(n)}.`],
  [
    /^Estás viendo datos de demostración\. Para ver tu cartera, poné los CSV de movimientos de tu broker en (.*) \((?:Configuración → Tus datos|ver README)\)\.$/s,
    "You're looking at demo data. To see your own portfolio, put your broker's transaction CSVs in $1 (Settings → Your data).",
  ],
  [/^No se pudo abrir la carpeta: (.*)$/s, "Couldn't open the folder: $1"],

  // ---------------------------------------------------------------- core/historical_curve.py
  [
    /^Se corrigieron picos aislados de un dia en los precios de yfinance \(saltos de mas de (\d+)% que se revierten al dia siguiente, tipicos errores de datos\): (.*)\.$/s,
    "Isolated one-day spikes in yfinance prices were corrected (jumps over $1% that reverse the next day, typical data errors): $2.",
  ],
  [
    /^(.*?): yfinance publica el precio en otra escala \(x(.*?) respecto de tus operaciones reales\); se corrigio en la curva historica\.$/s,
    "$1: yfinance publishes the price on a different scale (x$2 vs. your actual trades); corrected in the historical curve.",
  ],
  [
    /^(.*?): yfinance no tiene precio antes del (\S+) y ya tenias el activo; ese tramo se completo con (.*)\.$/s,
    (_tr, t, f, metodo) =>
      `${t}: yfinance has no price before ${f} and you already held the asset; that stretch was filled using ${
        metodo === "subyacente en EE.UU. x CCL" ? "the US underlying × CCL" : metodo === "interpolacion entre tus precios de operacion" ? "interpolation between your trade prices" : metodo
      }.`,
  ],
  [
    /^Sin precio historico en yfinance para: (.*?) \(tipico de bonos\/renta fija.*$/s,
    "No price history in yfinance for: $1 (typical of bonds/fixed income, e.g. AL30, GD38, which Yahoo Finance doesn't list under the .BA suffix). They're excluded from BOTH curves (Market value and Invested capital) so the comparison is fair: counting their cost in invested capital while valuing them at $0 would show an artificial loss.",
  ],
  [
    /^Sin precio historico en yfinance para el\/los benchmark\(s\): (.*?) \(misma convencion.*$/s,
    "No price history in yfinance for the benchmark(s): $1 (same CEDEAR/BYMA convention as the rest of the app). Those comparison lines are left out of the chart. Check 'benchmark_tickers' in portfolio_config.json ('meta' section).",
  ],
  [
    /^No se pudo obtener el CCL historico \((.*)\): los dividendos en dolares no se suman a la curva \(quedan subestimados\)\.$/s,
    "Couldn't get the historical CCL ($1): dollar dividends aren't added to the curve (they're understated).",
  ],
  [
    /^Sin datos de dividendos para (.*?): esa\(s\) linea\(s\) de comparacion usan solo precio.*$/s,
    "No dividend data for $1: those comparison lines use price only (no dividends), which slightly favors your portfolio in the comparison.",
  ],

  // ---------------------------------------------------------------- core/analytics.py
  [
    /^El riesgo del PORTAFOLIO se calculo renormalizando los pesos sin (.*?) \(sin historico disponible\).*$/s,
    "PORTFOLIO risk was calculated by renormalizing the weights without $1 (no history available): it doesn't represent 100% of your target portfolio, only the part with data.",
  ],
  [
    /^Sin historico suficiente en yfinance para: (.*?) \(sin datos, o menos de (\d+) dias.*$/s,
    "Not enough history in yfinance for: $1 (no data, or under $2 days, even via the underlying proxy, typical of a newly listed CEDEAR on BYMA). They're left out of the correlation matrix and risk metrics so they don't shorten the common analysis window for the other assets.",
  ],
  [
    /^(.*?): el CEDEAR \(\.BA\) tiene muy poco historico en yfinance.*$/s,
    "$1: the CEDEAR (.BA) has very little history in yfinance (typical of a recent BYMA listing), so the USD underlying ticker was used as a proxy. Unlike the other CEDEARs, the volatility/correlation of these assets does NOT include the CCL dollar effect.",
  ],
  [/^La configuracion no tiene ningun activo con un simbolo de yfinance resoluble\.$/, "The settings have no asset with a resolvable yfinance symbol."],

  // ---------------------------------------------------------------- core/macro_data.py y market_data.py
  [/^No se pudo actualizar (.*?) \((.*)\); se usa la ultima copia guardada localmente\.$/s, "Couldn't update $1 ($2); using the last locally saved copy."],
  [/^No hay datos de (.*?): la API no respondio \((.*)\) y no hay copia local\.$/s, "No $1 data: the API didn't respond ($2) and there's no local copy."],
  [/^No se pudo estimar el CCL: falta el precio de (.*?) en yfinance\.$/s, "Couldn't estimate the CCL: missing the price of $1 in yfinance."],

  // ---------------------------------------------------------------- core/rebalancer.py
  [
    /^No se pudo cotizar (.*?) \(0% Objetivo, ej\. una tenencia manual huerfana.*$/s,
    "Couldn't quote $1 (0% target, e.g. an orphan manual holding whose ticker didn't resolve). It doesn't affect the allocation because they'd never receive buys, but they're left out of the total value until they have a price.",
  ],
  [
    /^No se puede calcular el rebalanceo: falta el precio de (.*?)\. Esto casi siempre es Yahoo Finance.*$/s,
    "Can't calculate the rebalance: missing the price of $1. This is almost always Yahoo Finance temporarily rate-limiting requests (not a settings problem). The app already retries a couple of times before showing this error. Wait a minute and calculate again, or check your connection if it persists.",
  ],
  [
    /^(.*?) tienen 0% Objetivo \(huerfanos, ver core\/holdings\.py\).*$/s,
    "$1 have a 0% target (orphans, see core/holdings.py), so they show as 'Overweight' with a suggested sale of their WHOLE position. It's not an error: it's the same '0% target = never receives buys' logic applied the other way.",
  ],
  [
    /^'(.*?)' esta fuera de banda por su % actual, pero el Monto Nuevo alcanza.*$/s,
    "'$1' is outside the band by its current %, but the new money is enough to dilute its overweight without selling (its target in ARS, with the contribution added, ended up above its current value). No sale is suggested for this asset.",
  ],
  [
    /^'(.*?)' esta sobreponderado fuera de banda pero no tiene precio disponible.*$/s,
    "'$1' is overweight outside the band but has no price available to calculate how many units to sell, so it's left out of the sell orders.",
  ],
  [
    /^Ningun activo esta desviado mas de ([\d.]+) puntos porcentuales por ENCIMA de su objetivo.*$/s,
    "No asset is more than $1 percentage points ABOVE its target, and no new money was entered: there's no cash available to buy anything.",
  ],
  [
    /^No hay ningun activo desviado mas de ([\d.]+) puntos porcentuales por DEBAJO de su objetivo para reinvertir el efectivo disponible \((.*?)\).*$/s,
    "No asset is more than $1 percentage points BELOW its target to reinvest the available cash ($2), so it stays unallocated.",
  ],
  [
    /^Vender implica un posible impacto impositivo.*$/s,
    "Selling may have tax consequences (Argentine wealth/income tax depending on your situation) that this calculation does NOT estimate: net sale amounts are net of the broker's fee only, not of taxes. Review the tax impact of each sale before placing it.",
  ],
  [
    /^Vender puede tener impacto impositivo \(segun tu situacion fiscal.*?\(([\d.]+)% por operacion\)\.$/s,
    "Selling may have tax consequences (depending on your tax situation and the asset type) that this plan does NOT calculate: double-check before placing orders. Fees are estimates ($1% per trade).",
  ],
  [
    /^Vas a vender entero (.*?), que SI estan en tu objetivo.*$/s,
    "You're going to sell all of $1, which ARE in your target: the plan will partly buy them back if they end up below their %. If you only want to trim the excess, remove them from the list and use 'sell overweight'.",
  ],
  [/^No hay posicion valuada para vender: (.*)\.$/s, "No valued position to sell: $1."],
  [/^No se pudo distribuir el monto por deficit.*$/s, "The amount couldn't be split by deficit (sum of positive deficits <= 0), which should only happen with invalid settings. It was split by each asset's target % as a fallback, but check portfolio_config.json."],
  [/^El monto a invertir debe ser mayor a 0\.$/, "The amount to invest must be greater than 0."],
  [/^La banda de tolerancia debe ser mayor a 0 puntos porcentuales\.$/, "The tolerance band must be greater than 0 percentage points."],
  [/^El monto nuevo \(opcional\) no puede ser negativo\.$/, "The new money (optional) can't be negative."],
  [/^El monto nuevo no puede ser negativo\.$/, "The new money can't be negative."],

  // ---------------------------------------------------------------- core/config_manager.py (validacion del editor)
  [/^Los '% Objetivo Total' de Categorias suman ([\d.]+)% \(tienen que sumar 100%\)\.$/, "The categories' target % add up to $1% (they must add up to 100%)."],
  [/^Los activos de la categoria '(.*)' suman ([\d.]+)% \(tienen que sumar 100%\)\.$/s, (tr, c, p) => `The assets in category '${tr(c)}' add up to ${p}% (they must add up to 100%).`],
  [/^La categoria '(.*)' no tiene ningun activo asignado\..*$/s, (tr, c) => `Category '${tr(c)}' has no assets assigned. Add at least one or delete the category.`],
  [
    /^El activo '(.*?)' tiene la categoria '(.*?)', que no existe en la tabla de Categorias.*$/s,
    (tr, t, c) => `Asset '${t}' has category '${c === "(vacia)" ? "(empty)" : tr(c)}', which doesn't exist in the Categories table (did you delete it or spell it differently?).`,
  ],
  [/^Hay categorias duplicadas: (.*)\. Cada nombre debe ser unico\.$/s, "Duplicate categories: $1. Each name must be unique."],
  [/^Hay tickers duplicados en Activos: (.*)\. Cada Ticker debe ser unico\.$/s, "Duplicate tickers in Assets: $1. Each ticker must be unique."],
  [/^Hay una fila en 'Categorias' con el nombre vacio\..*$/s, "There's a row in Categories with an empty name. Fill it in or delete the row."],
  [/^Hay una fila en 'Activos' con el Ticker vacio\..*$/s, "There's a row in Assets with an empty ticker. Fill it in (e.g. 'TSLA') or delete the row."],
  [/^Al activo '(.*?)' le falta el 'Ticker de Mercado' \(ej\. 'TSLA\.BA'\)\.$/, "Asset '$1' is missing its yfinance ticker (e.g. 'TSLA.BA')."],
  [/^El activo '(.*?)' no puede tener a si mismo como Ticker Alias\.$/, "Asset '$1' can't be its own alias."],
  [/^El activo '(.*?)' no puede tener a si mismo como 'alias_ticker'\.$/, "Asset '$1' can't be its own alias."],
  [/^El Ticker Alias '(.*?)' del activo '(.*?)' ya es el Ticker propio de otro activo.*$/s, "Alias '$1' of asset '$2' is already another asset's own ticker in this table; it can't be both."],
  [/^No hay ningun activo cargado.*$/s, "There are no assets: add at least one row to the Assets table."],
  [/^El activo '(.*?)' tiene un Tipo invalido \('(.*?)'\)\. Debe ser uno de: (.*)\.$/s, "Asset '$1' has an invalid type ('$2'). It must be one of: $3."],
  [/^La categoria '(.*)' no existe\.$/, (tr, c) => `Category '${tr(c)}' doesn't exist.`],
  [/^Los 'objetivo_pct' de 'categorias' deben sumar 100%\. Suman (.*)%\.$/, "The categories' target % must add up to 100%. They add up to $1%."],
  [/^No se encontro el archivo de configuracion: (.*)$/s, "Settings file not found: $1"],
  [/^No se pudo leer '(.*?)': (.*)$/s, "Couldn't read '$1': $2"],

  // ---------------------------------------------------------------- core/manual_holdings.py
  [/^Hay una fila de Tenencias Manuales con el Ticker vacio\..*$/s, "There's a manual holdings row with an empty ticker. Fill it in or delete the row."],
  [/^La Cantidad de '(.*?)' no es un numero valido\.$/, "The quantity of '$1' isn't a valid number."],
  [/^La Cantidad de '(.*?)' tiene que ser mayor a 0.*$/s, "The quantity of '$1' must be greater than 0 (to remove a holding, delete the row instead of entering 0)."],
  [/^'(.*?)' deberia contener una lista de tenencias manuales\.$/, "'$1' should contain a list of manual holdings."],

  // ---------------------------------------------------------------- core/diario.py
  [/^Falta el ticker\.$/, "The ticker is missing."],
  [/^La accion tiene que ser una de: (.*)\.$/, "The action must be one of: $1."],
  [/^Escribi el motivo con un poco mas de detalle.*$/s, "Write the reason in a bit more detail (it's the most valuable part of the journal)."],
  [/^Falta el (.*?) de hoy para poder medir la decision mas adelante\.$/, "Today's $1 is missing, so the decision can't be measured later."],
  [/^El horizonte tiene que estar entre 1 y 120 meses\.$/, "The horizon must be between 1 and 120 months."],
  [/^No se pudo leer (.*?): (.*)$/s, "Couldn't read $1: $2"],
  [/^(.*?) no tiene el formato esperado \(una lista de decisiones\)\.$/, "$1 doesn't have the expected format (a list of decisions)."],
];

/** Textos fijos del motor que van directo al diccionario (sin datos adentro). */
export const MENSAJES_FIJOS_EN: Record<string, string> = {
  "Hace falta el dólar CCL histórico para valuar los dividendos en dólares.": "Historical CCL is needed to value dividends in dollars.",
  "No hay historia descargada para los escenarios (revisá tu conexión; se guarda en data/cache/stress/).":
    "No history downloaded for the scenarios (check your connection; it's saved in data/cache/stress/).",
  "No se pudo conectar con el motor de datos (backend Python).": "Couldn't connect to the data engine (Python backend).",
  "Cada peso convertido al dólar CCL del día en que se movió.": "Each peso converted at the CCL dollar rate on the day it moved.",
  "Pesos corrientes, sin ajustar por inflación ni por dólar.": "Nominal pesos, not adjusted for inflation or the dollar.",
  "Pesos ajustados por inflación (IPC), expresados en pesos de hoy.": "Pesos adjusted for inflation (CPI), in today's pesos.",
  "El CCL historico vino con un formato inesperado.": "Historical CCL came in an unexpected format.",
  "El CCL historico vino vacio.": "Historical CCL came back empty.",
  "La inflacion vino con un formato inesperado.": "Inflation data came in an unexpected format.",
  "La serie de inflacion vino vacia.": "The inflation series came back empty.",
  "Fuera de objetivo": "Off-target",
  "Venta total elegida": "Full sale chosen",
};
