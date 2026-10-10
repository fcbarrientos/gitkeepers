import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import { setToken } from "../auth/token";
import { ToastProvider } from "../components/Toast";
import { I18nProvider } from "../i18n/i18n";
import { PROVIDER_FUTURE, ROUTER_FUTURE, routes } from "../routes";

/** Render the whole app at `path`. With signedIn, a token is stored; mock "GET /auth/me" too. */
export function renderApp(path: string, options: { signedIn?: boolean } = {}) {
  if (options.signedIn) setToken("test-token");
  const router = createMemoryRouter(routes, { initialEntries: [path], future: ROUTER_FUTURE });
  const user = userEvent.setup();
  render(
    <I18nProvider>
      <ToastProvider>
        <AuthProvider>
          <RouterProvider router={router} future={PROVIDER_FUTURE} />
        </AuthProvider>
      </ToastProvider>
    </I18nProvider>,
  );
  return { router, user };
}

export function renderWithI18n(ui: ReactElement) {
  return { user: userEvent.setup(), ...render(<I18nProvider>{ui}</I18nProvider>) };
}
