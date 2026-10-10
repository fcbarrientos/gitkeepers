import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { ToastProvider } from "./components/Toast";
import { I18nProvider } from "./i18n/i18n";
import { PROVIDER_FUTURE, ROUTER_FUTURE, routes } from "./routes";
import "./styles/tokens.css";
import "./styles/base.css";

const router = createBrowserRouter(routes, { future: ROUTER_FUTURE });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <ToastProvider>
        <AuthProvider>
          <RouterProvider router={router} future={PROVIDER_FUTURE} />
        </AuthProvider>
      </ToastProvider>
    </I18nProvider>
  </StrictMode>,
);
