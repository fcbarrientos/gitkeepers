import { screen, within } from "@testing-library/react";
import type { ReportDraft, ReportFigures, ReportSummary } from "../api/types";
import { admin, bpForm } from "../test/fixtures";
import { callsTo, mockApi, signedInAs, type Route } from "../test/http";
import { renderApp } from "../test/render";

const figures = (visits: number): ReportFigures => ({
  start: "2026-10-05", end: "2026-10-11", visits: { total: visits, final: visits, by_form: { bp_followup: visits } },
  new_households: 1, new_patients: 2, follow_ups_completed: 0, follow_ups_overdue: 1, referral_flags: 1,
  referrals_issued: 1, referrals_by_reason: { "Very high BP": 1, manual: 2 },
  supplies: [{ name: "ORS", unit: "sachets", received: 20, distributed: 15 }], low_stock_items: ["ORS"],
});
const summary: ReportSummary = { period: "week", current: figures(7), previous: figures(3), unsynced_records: 4 };
const draft: ReportDraft = {
  id: "d1", period: "week", start_date: "2026-10-05", end_date: "2026-10-11", figures: summary,
  text: "Consider a BP screening day.", status: "draft", model: "fake", created_by: "u1", approved_by: null,
  created_at: "2026-10-10", updated_at: "2026-10-10",
};

function backend(extra: Record<string, Route> = {}) {
  return mockApi({
    ...signedInAs(admin),
    "GET /reports/summary": [200, summary],
    "GET /reports/drafts": [200, []],
    "GET /ai/status": [200, { available: true, model: "Qwen" }],
    "GET /forms": [200, [bpForm]],
    ...extra,
  });
}

describe("reports", () => {
  it("compares with the previous period and warns about unsynced records", async () => {
    const { calls, } = backend();
    const { user } = renderApp("/reports?date=2026-10-10", { signedIn: true });
    expect(await screen.findByText("4 records are not yet transferred to the RHU, so RHU figures may differ.")).toBeInTheDocument();
    const visitsCard = () => screen.getByRole("heading", { name: "Visits" }).closest("section")!;
    expect(within(visitsCard()).getByText("previous: 3")).toBeInTheDocument();
    expect(screen.getByText("Referrals without a rule flag")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Period"), "month");
    await screen.findAllByText("previous: 3");
    expect(calls.map((c) => c.path)).toContain("/reports/summary?period=month&date=2026-10-10");
  });

  it("generates, edits and approves an AI draft", async () => {
    const { calls } = backend({
      "POST /reports/drafts": [201, draft],
      "PATCH /reports/drafts/d1": [200, { ...draft, status: "approved", text: "Edited." }],
    });
    const { user } = renderApp("/reports?date=2026-10-10", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Generate AI draft" }));
    const text = await screen.findByLabelText("Draft text");
    expect(text).toHaveValue("Consider a BP screening day.");
    await user.clear(text);
    await user.type(text, "Edited.");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Summary approved")).toBeInTheDocument();
    expect(callsTo(calls, "PATCH", "/reports/drafts/d1")[0].body).toEqual({ text: "Edited.", status: "approved" });
  });

  it("falls back to writing by hand when the AI is unavailable", async () => {
    const { calls } = backend({
      "POST /reports/drafts": [503, { detail: "AI assistant unavailable — please fill in the form manually" }],
      "POST /reports/drafts/manual": [201, { ...draft, id: "d2", model: null, text: "Hand written." }],
      "PATCH /reports/drafts/d2": [200, { ...draft, id: "d2", status: "approved" }],
    });
    const { user } = renderApp("/reports?date=2026-10-10", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Generate AI draft" }));
    expect(await screen.findByText("AI assistant unavailable — write the summary by hand.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Write without AI" }));
    await user.type(screen.getByLabelText("Draft text"), "Hand written.");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("Summary approved");
    expect(callsTo(calls, "POST", "/reports/drafts/manual")[0].body).toEqual({
      period: "week", date: "2026-10-10", text: "Hand written.",
    });
  });
});
