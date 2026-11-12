import { useEffect, useState } from "react";
import { abrirCarpeta, getDatosUsuario, type DatosUsuario } from "../../api";
import { Card } from "../../components/ui";
import { t, tb, tm } from "../../i18n";

/**
 * Donde estan los datos del usuario y un boton para abrir la carpeta de los
 * CSV: es el primer paso para alguien que recien instala la app.
 */
export function TusDatos() {
  const [d, setD] = useState<DatosUsuario | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDatosUsuario().then(setD, (e: Error) => setError(e.message));
  }, []);

  const abrir = () => abrirCarpeta().catch((e: Error) => setError(e.message));

  return (
    <Card titulo="Tus datos" sub="Los movimientos de tu broker se leen de esta carpeta">
      {d && (
        <>
          <div className="datos-ruta">
            <code className="mono">{d.movimientos}</code>
            <button className="btn-secundario chico" onClick={abrir}>
              {t("Abrir carpeta")}
            </button>
          </div>
          <div className={`alerta ${d.demo ? "" : "ok"}`}>
            {d.demo
              ? tb("Todavía no hay CSV tuyos: la app muestra **datos de demostración**.")
              : tb(d.csv === 1 ? "Se está leyendo **1 archivo CSV**." : "Se están leyendo **{n} archivos CSV**.", { n: d.csv })}
          </div>
          <ol className="datos-pasos">
            <li>{t("En Cocos Capital, exportá los movimientos de tu cuenta como CSV.")}</li>
            <li>{t("Guardá el archivo en esta carpeta. Podés sumar exports nuevos cuando quieras: se leen todos y los repetidos se descartan.")}</li>
            <li>{t("Tocá el botón de actualizar (arriba a la derecha) y armá tu cartera objetivo acá abajo.")}</li>
          </ol>
        </>
      )}
      {error && <div className="alerta error">{tm(error)}</div>}
    </Card>
  );
}
