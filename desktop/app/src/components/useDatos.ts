import { useEffect, useState } from "react";

/**
 * Pide datos al backend y los vuelve a pedir cuando cambia alguna dependencia.
 * Ignora respuestas viejas si las dependencias cambiaron mientras tanto.
 */
export function useDatos<T>(pedir: () => Promise<T>, deps: unknown[]) {
  const [datos, setDatos] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vivo = true;
    setCargando(true);
    pedir()
      .then((d) => {
        if (vivo) {
          setDatos(d);
          setError(null);
        }
      })
      .catch((e) => vivo && setError((e as Error).message))
      .finally(() => vivo && setCargando(false));
    return () => {
      vivo = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { datos, error, cargando };
}
