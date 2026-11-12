import { useEffect, useRef, useState } from "react";
import { getTirCuenta, guardarOtrosCuenta, type TirCuenta as TirCuentaT } from "../../api";
import { Card, MiniKpi, MontoInput } from "../../components/ui";
import { ars, dinero, fpct, pp } from "../../format";
import { t, tm } from "../../i18n";

/**
 * TIR de TODA la cuenta (incluida la plata quieta) vs. la TIR solo de
 * acciones. El "efectivo + FCI" no sale del CSV: lo carga el usuario.
 */
export function TirCuenta({ version }: { version: number }) {
  const [datos, setDatos] = useState<TirCuentaT | null>(null);
  const [otros, setOtros] = useState<number | null>(null);
  const [guardado, setGuardado] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [estado, setEstado] = useState<string | null>(null);
  const primera = useRef(true);

  // Primera carga: usa el monto recordado en config/metas.json.
  useEffect(() => {
    getTirCuenta()
      .then((d) => {
        setDatos(d);
        setOtros(d.otros_ars);
        setGuardado(d.otros_ars);
      })
      .catch((e) => setError((e as Error).message));
  }, [version]);

  // Al tipear, recalcula (sin guardar) con un pequeno retardo.
  useEffect(() => {
    if (otros == null) return;
    if (primera.current) {
      primera.current = false;
      return;
    }
    const t = setTimeout(() => {
      getTirCuenta(otros)
        .then((d) => (setDatos(d), setError(null)))
        .catch((e) => setError((e as Error).message));
    }, 350);
    return () => clearTimeout(t);
  }, [otros]);

  const recordar = async () => {
    if (otros == null) return;
    try {
      await guardarOtrosCuenta(otros);
      setGuardado(otros);
      setEstado(t("Guardado: se usa la próxima vez que abras la app."));
    } catch (e) {
      setEstado((e as Error).message);
    }
  };

  const u = datos?.en_usd ? "usd" : "ars";
  return (
    <Card titulo="Toda tu cuenta" sub="Lo que rindió la plata que mandaste a Cocos, incluida la que estuvo quieta">
      <div className="tir-controles">
        <label className="campo">
          <span>{t("Efectivo + FCI + otros en tu cuenta hoy (lo ves en Cocos)")}</span>
          <MontoInput chico valor={otros ?? 0} onChange={setOtros} onEnter={recordar} />
        </label>
        <button className="btn-secundario" onClick={recordar} disabled={otros == null || otros === guardado}>
          {otros === guardado ? t("Recordado") : t("Recordar este monto")}
        </button>
      </div>
      {estado && <div className="cfg-nota faint">{estado}</div>}
      {error && <div className="alerta error">{tm(error)}</div>}
      {datos && (
        <>
          <div className="mini-kpis cuatro" style={{ marginTop: 14 }}>
            <MiniKpi etq={t("TIR de toda la cuenta ({m})", { m: datos.en_usd ? "USD" : "ARS" })} val={fpct(datos.tir_cuenta)} fuerte tooltip="XIRR de tus depósitos y retiros contra lo que vale hoy la cuenta completa." />
            <MiniKpi etq="TIR solo acciones" val={fpct(datos.tir_acciones)} />
            <MiniKpi etq="Diferencia" val={pp(datos.diferencia)} tooltip="Negativa = la plata que no estaba en acciones rindió menos y bajó el resultado total. Es el costo de tener plata quieta." />
            <MiniKpi etq="Ganancia total" val={dinero(datos.ganancia, u, true)} />
          </div>
          {!otros && <div className="alerta" style={{ marginTop: 12 }}>{t("Cargá el efectivo + FCI que ves en Cocos: si no, la cuenta parece valer menos de lo que vale y la TIR da de menos.")}</div>}
          <div className="cfg-nota faint">
            {t("Valor de la cuenta usado: acciones {a} + otros {o}. Flujos: {f} depósitos/retiros (en pesos y en dólares, cada uno a su CCL). Con períodos menores a un año la TIR anualizada es una extrapolación.", { a: ars(datos.acciones_ars), o: ars(datos.otros_ars), f: datos.flujos })}
          </div>
        </>
      )}
    </Card>
  );
}
