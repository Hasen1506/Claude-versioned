import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "@fontsource/ibm-plex-mono/latin-700.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-700.css";
import { App } from "./App";
import { applyTheme, readTheme } from "./components/ui";
import "./styles.css";
import { store } from "./state/store";

applyTheme(readTheme());

// For diagnosing a large company in a test browser: `localStorage["scp.debug"] = "1"` puts the state in reach.
try {
  if (localStorage.getItem("scp.debug")) (window as unknown as { scpState: () => unknown }).scpState = () => store.get();
} catch {
  /* no storage */
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
