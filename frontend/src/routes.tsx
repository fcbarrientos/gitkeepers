import type { RouteObject } from "react-router-dom";
import { RequireAdmin, RequireAuth } from "./auth/guards";
import { Layout } from "./components/Layout";
import { CheckupPage } from "./pages/CheckupPage";
import { ComingSoonPage } from "./pages/ComingSoonPage";
import { DashboardPage } from "./pages/DashboardPage";
import { FollowUpsPage } from "./pages/FollowUpsPage";
import { HouseholdNewPage } from "./pages/HouseholdNewPage";
import { HouseholdPage } from "./pages/HouseholdPage";
import { HouseholdsPage } from "./pages/HouseholdsPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PatientPage } from "./pages/PatientPage";
import { PatientsPage } from "./pages/PatientsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SignupPage } from "./pages/SignupPage";
import { UsersPage } from "./pages/UsersPage";

export const ROUTER_FUTURE = {
  v7_relativeSplatPath: true,
  v7_fetcherPersist: true,
  v7_normalizeFormMethod: true,
  v7_partialHydration: true,
  v7_skipActionErrorRevalidation: true,
} as const;
export const PROVIDER_FUTURE = { v7_startTransition: true } as const;

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/signup", element: <SignupPage /> },
  {
    path: "/",
    element: <RequireAuth><Layout /></RequireAuth>,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "profile", element: <ProfilePage /> },
      { path: "admin/users", element: <RequireAdmin><UsersPage /></RequireAdmin> },
      { path: "referrals", element: <ComingSoonPage titleKey="nav.referrals" /> },
      { path: "supplies", element: <ComingSoonPage titleKey="nav.supplies" /> },
      { path: "reports", element: <ComingSoonPage titleKey="nav.reports" /> },
      { path: "sync", element: <ComingSoonPage titleKey="nav.sync" /> },
      { path: "households", element: <HouseholdsPage /> },
      { path: "households/new", element: <HouseholdNewPage /> },
      { path: "households/:householdId", element: <HouseholdPage /> },
      { path: "patients", element: <PatientsPage /> },
      { path: "patients/:patientId", element: <PatientPage /> },
      { path: "patients/:patientId/visits/new", element: <CheckupPage /> },
      { path: "visits/:visitId", element: <CheckupPage /> },
      { path: "follow-ups", element: <FollowUpsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
