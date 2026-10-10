import { screen, within } from "@testing-library/react";
import { admin, dashboard, page, volunteer } from "../test/fixtures";
import { callsTo, mockApi, signedInAs, type Route } from "../test/http";
import { renderApp } from "../test/render";

const homeData: Record<string, Route> = {
  "GET /dashboard": [200, dashboard], "GET /visits": [200, page([])], "GET /forms": [200, []],
  "GET /follow-ups": [200, page([])], "GET /referrals": [200, page([])], "GET /sync/bundles": [200, []],
  "GET /supplies": [200, []], "GET /ai/status": [200, dashboard.ai],
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
    expect(await screen.findByRole("heading", { level: 1, name: /Ada/ })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });
});

describe("app shell", () => {
  it("shows a retry screen when the server stops responding", async () => {
    mockApi({ ...signedInAs(admin), ...homeData, "GET /dashboard": "network" });
    renderApp("/", { signedIn: true });
    expect(await screen.findByRole("heading", { name: "Can't reach the RuPort AI server on this laptop" }))
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
  it("shows the real counts and links each one to its filtered list", async () => {
    mockApi({ ...signedInAs(admin), ...homeData });
    renderApp("/", { signedIn: true });
    const stats = await screen.findByRole("navigation", { name: "Key figures" });
    const overdue = within(stats).getByRole("link", { name: /Overdue follow-ups/ });
    expect(overdue).toHaveAttribute("href", "/follow-ups?state=overdue");
    expect(within(overdue).getByText("3")).toBeInTheDocument();
    expect(within(stats).getByRole("link", { name: /Open referral flags/ })).toHaveAttribute("href", "/referrals");
    expect(within(stats).getByRole("link", { name: /Not yet synced/ })).toHaveAttribute("href", "/sync");
    expect(within(stats).getByRole("link", { name: /Patients/ })).toHaveAttribute("href", "/patients");
  });

  it("lists what needs attention, most urgent first, without inventing items", async () => {
    mockApi({ ...signedInAs(admin), ...homeData });
    renderApp("/", { signedIn: true });
    const panel = (await screen.findByRole("heading", { name: "Needs attention" })).closest("section")!;
    const items = within(panel).getAllByRole("link").map((link) => link.textContent);
    expect(items[0]).toContain("Overdue follow-ups: 3");
    expect(items[1]).toContain("Referral flags to review: 2");
    expect(items.join(" ")).toContain("Supplies at or below low-stock level: 1");
    expect(items).toHaveLength(6);
  });

  it("shows badges in the sidebar from the dashboard counts", async () => {
    mockApi({ ...signedInAs(admin), ...homeData });
    renderApp("/", { signedIn: true });
    const nav = await screen.findByRole("navigation", { name: "Main menu" });
    expect(await within(nav).findByRole("link", { name: /Follow-ups.*4 pending/ })).toHaveAttribute("href", "/follow-ups");
    expect(within(nav).getByRole("link", { name: /Checkups.*1 pending/ })).toHaveAttribute("href", "/checkups");
  });
});

describe("checkups list", () => {
  it("filters checkups by status through the URL", async () => {
    const { calls } = mockApi({ ...signedInAs(admin), "GET /visits": [200, page([])], "GET /forms": [200, []] });
    const { user, router } = renderApp("/checkups", { signedIn: true });
    await user.click(await screen.findByRole("tab", { name: "Draft" }));
    expect(router.state.location.search).toBe("?status=draft");
    await screen.findByText("No checkups match these filters.");
    expect(calls.map((c) => c.path)).toContain("/visits?status=draft&limit=25&offset=0");
  });
});
