import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource-variable/geist";
import "@fontsource-variable/archivo";
import "@fontsource/barlow-condensed/500.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "./styles/tokens.css";
import "./styles/app.css";
import App from "./App.tsx";
import { TemaProvider } from "./theme/tema";
import { IdiomaProvider } from "./i18n";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <IdiomaProvider>
      {(idioma) => (
        <TemaProvider>
          {/* al cambiar de idioma la app se vuelve a montar con los textos y formatos nuevos */}
          <App key={idioma} />
        </TemaProvider>
      )}
    </IdiomaProvider>
  </StrictMode>,
);
