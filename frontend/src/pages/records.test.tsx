import { screen } from "@testing-library/react";
import { admin, bpForm, childForm, followUp, household, page, patient, visit } from "../test/fixtures";
import { callsTo, mockApi, signedInAs } from "../test/http";
import { renderApp } from "../test/render";

const summary = { id: "h1", barangay: "San Roque", sitio: "Malinis", address_line: null, contact_number: null,
  updated_at: "2026-10-01", member_count: 1, head_name: "Ana Dela Cruz" };

describe("households", () => {
  it("searches households", async () => {
    const { calls } = mockApi({ ...signedInAs(admin), "GET /households": [200, page([summary])] });
    const { user } = renderApp("/households", { signedIn: true });
    expect(await screen.findByText("Ana Dela Cruz")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search by name or place"), "Ana");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText("Ana Dela Cruz");
    expect(calls.map((c) => c.path)).toContain("/households?q=Ana&limit=25&offset=0");
  });

  it("registers a household with its first member", async () => {
    const { calls } = mockApi({
      ...signedInAs(admin),
      "POST /households": [201, household],
      "GET /households/h1": [200, household],
    });
    const { user } = renderApp("/households/new", { signedIn: true });
    await user.type(await screen.findByLabelText("Barangay"), "San Roque");
    await user.type(screen.getByLabelText("Full name"), "Ana Dela Cruz");
    await user.click(screen.getByRole("button", { name: "Register household" }));
    expect(await screen.findByRole("heading", { name: "San Roque" })).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/households")[0].body).toEqual({
      barangay: "San Roque", sitio: null, address_line: null, contact_number: null,
      members: [{ full_name: "Ana Dela Cruz", sex: null, birth_date: null, contact_number: null,
        relationship_to_head: null, is_household_head: true }],
    });
  });
});

describe("patient page", () => {
  it("shows the visit timeline and starts a checkup with the chosen form", async () => {
    mockApi({
      ...signedInAs(admin),
      "GET /patients/p1": [200, patient],
      "GET /forms": [200, [bpForm, childForm]],
      "GET /patients/p1/visits": [200, page([visit({ id: "v2", status: "final" }), visit({ id: "v1" })])],
      "GET /follow-ups": [200, page([followUp()])],
    });
    const { user, router } = renderApp("/patients/p1", { signedIn: true });
    expect(await screen.findByRole("heading", { name: "Ana Dela Cruz" })).toBeInTheDocument();
    expect(await screen.findByText("Final")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("BP recheck")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Checkup form"), "child_growth");
    await user.click(screen.getByRole("button", { name: "Start checkup" }));
    expect(router.state.location.pathname).toBe("/patients/p1/visits/new");
    expect(router.state.location.search).toBe("?form=child_growth");
  });
});
