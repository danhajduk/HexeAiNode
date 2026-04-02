import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./theme/index.css";
import { initTheme } from "./theme/theme";

initTheme();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
