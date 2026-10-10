import { screen, within } from "@testing-library/react";
import { admin, dashboard, page, volunteer } from "../test/fixtures";
import { callsTo, mockApi, signedInAs, type Route } from "../test/http";
import { renderApp } from "../test/render";

const homeData: Record<string, Route> = {
  "GET /dashboard": [200, dashboard], "GET /visits": [200, page([])], "GET /forms": [200, []],
};

describe("signing in", () => {
  it("sends signed-out visitors to the sign-in page", async () => {
    mockApi({});
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("returns to the page the user wanted after signing in", async () => {
    mockApi({ "POST /auth/login": [200, { token: "t1", expires_at: "2026-10-17", user: admin }] });
    const { user } = renderApp("/profile");
    await user.type(await screen.findByLabelText("Username or email"), "admin");
    await user.type(screen.getByLabelText("Password"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Profile" })).toBeInTheDocument();
  });

  it("shows the backend's reason when sign-in is refused", async () => {
    mockApi({ "POST /auth/login": [403, { detail: "Account awaiting admin approval" }] });
    const { user } = renderApp("/login");
    await user.type(await screen.findByLabelText("Username or email"), "ben");
    await user.type(screen.getByLabelText("Password"), "secret123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Account awaiting admin approval");
  });

  it("tells a new volunteer to wait for approval", async () => {
    mockApi({ "POST /auth/signup": [201, { ...volunteer, status: "pending" }] });
    const { user } = renderApp("/signup");
    await user.type(await screen.findByLabelText("Username"), "bhw.ben");
    await user.type(screen.getByLabelText("Full name"), "Ben Volunteer");
    await user.type(screen.getByLabelText("Password"), "secret123");
    await user.click(screen.getByRole("button", { name: "Create an account" }));
    expect(await screen.findByRole("heading", { name: "Waiting for approval" })).toBeInTheDocument();
  });

  it("returns to the same page after the session expires mid-session", async () => {
    let dashboardCalls = 0;
    mockApi({
      ...signedInAs(admin),
      ...homeData,
      "GET /dashboard": () => (++dashboardCalls === 1 ? [401, { detail: "Not signed in" }] : [200, dashboard]),
      "POST /auth/login": [200, { token: "t2", expires_at: "2026-10-17", user: admin }],
    });
    const { user, router } = renderApp("/", { signedIn: true });
    await user.type(await screen.findByLabelText("Username or email"), "admin");
    await user.type(screen.getByLabelText("Password"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });
});

describe("app shell", () => {
  it("shows a retry screen when the server stops responding", async () => {
    mockApi({ ...signedInAs(admin), ...homeData, "GET /dashboard": "network" });
    renderApp("/", { signedIn: true });
    expect(await screen.findByRole("heading", { name: "Can't reach the GitKeepers server on this laptop" }))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("keeps volunteers out of account administration", async () => {
    mockApi({ ...signedInAs(volunteer) });
    renderApp("/admin/users", { signedIn: true });
    expect(await screen.findByText("You don't have access to this page.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Accounts" })).not.toBeInTheDocument();
  });

  it("lets an admin approve a pending account", async () => {
    const pending = { ...volunteer, id: "u3", status: "pending" as const };
    const { calls } = mockApi({
      ...signedInAs(admin),
      "GET /users": [200, page([pending])],
      "PATCH /users/u3": [200, { ...pending, status: "active" }],
    });
    const { user } = renderApp("/admin/users", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    expect(callsTo(calls, "PATCH", "/users/u3")[0].body).toEqual({ status: "active" });
  });
});

describe("dashboard", () => {
  it("shows the counts and links them, but not the coming-soon cards", async () => {
    mockApi({ ...signedInAs(admin), ...homeData });
    renderApp("/", { signedIn: true });
    const overdue = (await screen.findByRole("heading", { name: "Overdue" })).closest("a");
    expect(overdue).toHaveAttribute("href", "/follow-ups?state=overdue");
    expect(within(overdue!).getByText("3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Referrals" }).closest("a")).toBeNull();
  });
});
