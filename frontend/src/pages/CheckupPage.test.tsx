import { screen, within } from "@testing-library/react";
import { addDays, todayIso } from "../lib/dates";
import { admin, bpForm, page, patient, visit } from "../test/fixtures";
import { callsTo, mockApi, signedInAs, type Route } from "../test/http";
import { renderApp } from "../test/render";

const NEW = "/patients/p1/visits/new?form=bp_followup";

function backend(extra: Record<string, Route> = {}) {
  return mockApi({
    ...signedInAs(admin),
    "GET /ai/status": [200, { available: true, model: "Qwen3-4B-Q4_K_M.gguf" }],
    "GET /patients/p1": [200, patient],
    "GET /forms/bp_followup": [200, bpForm],
    "GET /follow-ups": [200, page([])],
    ...extra,
  });
}

const field = (name: string) => document.querySelector(`[data-field="${name}"]`) as HTMLElement;

describe("checkup screen", () => {
  it("falls back to manual entry when the AI is unavailable", async () => {
    backend({ "POST /patients/p1/suggestions": [503, { detail: "AI assistant unavailable — please fill in the form manually" }] });
    const { user } = renderApp(NEW, { signedIn: true });
    await user.type(await screen.findByLabelText("Visit note"), "BP 150/95");
    await user.click(screen.getByRole("button", { name: "Fill from note" }));
    expect(await screen.findByText("AI assistant unavailable — please fill in the form manually")).toBeInTheDocument();
    await user.type(screen.getByLabelText("BP systolic (mmHg)"), "140");
    expect(screen.getByLabelText("BP systolic (mmHg)")).toHaveValue("140");
  });

  it("fills from a note, keeps typed values, and saves a draft with AI provenance", async () => {
    const { calls } = backend({
      "POST /patients/p1/suggestions": [200, {
        suggestion_id: "s1", form_type: "bp_followup", missing: ["pulse_bpm"], problems: [],
        values: { bp_systolic: 150, bp_diastolic: 95, headache: true, pulse_bpm: null },
      }],
      "POST /patients/p1/visits": [201, visit({ id: "v9" })],
      "GET /visits/v9": [200, visit({ id: "v9" })],
    });
    const { user, router } = renderApp(NEW, { signedIn: true });
    await user.type(await screen.findByLabelText("BP systolic (mmHg)"), "140");
    await user.type(screen.getByLabelText("Visit note"), "BP 150/95, masakit ulo");
    await user.click(screen.getByRole("button", { name: "Fill from note" }));
    expect(await screen.findByText("Not found in the note: Pulse (bpm)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept all" }));
    expect(within(field("bp_systolic")).getByText("AI suggests: 150")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Draft saved")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/patients/p1/visits")[0].body).toEqual({
      form_type: "bp_followup", visit_date: todayIso(), note: "BP 150/95, masakit ulo", status: "draft",
      values: { bp_systolic: 140, bp_diastolic: 95, headache: true },
      suggestion_id: "s1", ai_accepted_fields: ["bp_diastolic", "headache"],
    });
    expect(router.state.location.pathname).toBe("/visits/v9");
  });

  it("shows validation errors on their fields and the rest above the form", async () => {
    backend({ "POST /patients/p1/visits": [422, { detail: ["bp_systolic: required", "visit_date: cannot be in the future"] }] });
    const { user } = renderApp(NEW, { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Save draft" }));
    expect(await within(field("bp_systolic")).findByText("required")).toBeInTheDocument();
    expect(screen.getByText("visit_date: cannot be in the future")).toBeInTheDocument();
  });

  it("asks before finalizing and sends the follow-up only then", async () => {
    const { calls } = backend({
      "POST /patients/p1/visits": [201, visit({ id: "v9", status: "final" })],
      "GET /visits/v9": [200, visit({ id: "v9", status: "final" })],
    });
    const { user } = renderApp(NEW, { signedIn: true });
    await user.type(await screen.findByLabelText("BP systolic (mmHg)"), "150");
    await user.type(screen.getByLabelText("BP diastolic (mmHg)"), "95");
    await user.click(screen.getByLabelText("Schedule a follow-up"));
    await user.click(screen.getByRole("button", { name: "Finalize" }));
    const dialog = screen.getByRole("dialog", { name: "Finalize this visit?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(callsTo(calls, "POST", "/patients/p1/visits")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Finalize" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Finalize" }));
    expect(await screen.findByText("Visit finalized")).toBeInTheDocument();
    const body = callsTo(calls, "POST", "/patients/p1/visits")[0].body;
    expect(body.status).toBe("final");
    expect(body.follow_up).toEqual({ due_date: addDays(todayIso(), 30), reason: null });
  });

  it("creates one visit when Save is double-clicked", async () => {
    const { calls } = backend({
      "POST /patients/p1/visits": [201, visit({ id: "v9" })],
      "GET /visits/v9": [200, visit({ id: "v9" })],
    });
    const { user } = renderApp(NEW, { signedIn: true });
    await user.dblClick(await screen.findByRole("button", { name: "Save draft" }));
    await screen.findByText("Draft saved");
    expect(callsTo(calls, "POST", "/patients/p1/visits")).toHaveLength(1);
  });

  it("opens a final visit read-only with provenance", async () => {
    backend({
      "GET /visits/v1": [200, visit({
        status: "final", finalized_at: "2026-10-10 09:00:00", values: { bp_systolic: 150, bp_diastolic: 95 },
        sources: { bp_systolic: "ai_accepted", bp_diastolic: "manual" },
      })],
    });
    renderApp("/visits/v1", { signedIn: true });
    expect(await screen.findByLabelText("BP systolic (mmHg)")).toHaveValue("150");
    expect(screen.getByLabelText("BP systolic (mmHg)")).toHaveAttribute("readonly");
    expect(within(field("bp_systolic")).getByText("AI accepted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  });

  it("refuses to save while a number field holds invalid text", async () => {
    const { calls } = backend({ "POST /patients/p1/visits": [201, visit({ id: "v9" })] });
    const { user } = renderApp(NEW, { signedIn: true });
    await user.type(await screen.findByLabelText("Weight (kg)"), "37,5");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Fix the highlighted fields before saving.")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/patients/p1/visits")).toHaveLength(0);
  });

  it("keeps the follow-up choices after the first draft save", async () => {
    backend({
      "POST /patients/p1/visits": [201, visit({ id: "v9" })],
      "GET /visits/v9": [200, visit({ id: "v9" })],
    });
    const { user, router } = renderApp(NEW, { signedIn: true });
    await user.click(await screen.findByLabelText("Schedule a follow-up"));
    await user.type(screen.getByLabelText("Reason"), "BP recheck");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await screen.findByText("Draft saved");
    await screen.findByRole("heading", { name: "Blood pressure follow-up" });
    expect(router.state.location.pathname).toBe("/visits/v9");
    expect(screen.getByLabelText("Schedule a follow-up")).toBeChecked();
    expect(screen.getByLabelText("Reason")).toHaveValue("BP recheck");
  });

  it("restores the unsaved form after the session expires and the user signs in again", async () => {
    backend({
      "POST /patients/p1/visits": [401, { detail: "Session expired" }],
      "POST /auth/login": [200, { token: "t2", expires_at: "2026-10-17", user: admin }],
    });
    const { user } = renderApp(NEW, { signedIn: true });
    await user.type(await screen.findByLabelText("BP systolic (mmHg)"), "150");
    await user.type(screen.getByLabelText("Visit note"), "nahihilo");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await user.type(await screen.findByLabelText("Username or email"), "admin");
    await user.type(screen.getByLabelText("Password"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByLabelText("BP systolic (mmHg)")).toHaveValue("150");
    expect(screen.getByLabelText("Visit note")).toHaveValue("nahihilo");
  });

  it("asks before leaving with unsaved changes", async () => {
    backend({ "GET /forms": [200, [bpForm]], "GET /patients/p1/visits": [200, page([])] });
    const { user, router } = renderApp(NEW, { signedIn: true });
    await user.type(await screen.findByLabelText("BP systolic (mmHg)"), "150");
    await user.click(screen.getByRole("link", { name: "Ana Dela Cruz" }));
    const dialog = await screen.findByRole("dialog", { name: "Leave without saving?" });
    await user.click(within(dialog).getByRole("button", { name: "Leave" }));
    expect(router.state.location.pathname).toBe("/patients/p1");
  });
});
