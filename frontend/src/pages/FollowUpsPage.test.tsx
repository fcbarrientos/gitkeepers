import { fireEvent, screen, within } from "@testing-library/react";
import { admin, followUp, page } from "../test/fixtures";
import { callsTo, mockApi, signedInAs } from "../test/http";
import { renderApp } from "../test/render";

function backend() {
  return mockApi({
    ...signedInAs(admin),
    "GET /follow-ups": [200, page([followUp()])],
    "POST /follow-ups/f1/complete": [200, followUp({ status: "completed", state: "completed" })],
    "PATCH /follow-ups/f1": [200, followUp()],
  });
}

describe("follow-ups", () => {
  it("opens the tab named in the URL", async () => {
    const { calls } = backend();
    renderApp("/follow-ups?state=due", { signedIn: true });
    expect(await screen.findByRole("tab", { name: "Due today" })).toHaveAttribute("aria-selected", "true");
    await screen.findByText("Ana Dela Cruz");
    expect(calls.map((c) => c.path)).toContain("/follow-ups?state=due&limit=25&offset=0");
  });

  it("marks a follow-up done", async () => {
    const { calls } = backend();
    const { user } = renderApp("/follow-ups", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Mark done" }));
    expect(await screen.findByText("Follow-up marked done")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/follow-ups/f1/complete")).toHaveLength(1);
  });

  it("reschedules a follow-up", async () => {
    const { calls } = backend();
    const { user } = renderApp("/follow-ups", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Reschedule" }));
    fireEvent.change(screen.getByLabelText("New date"), { target: { value: "2026-12-01" } });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Follow-up rescheduled");
    expect(callsTo(calls, "PATCH", "/follow-ups/f1")[0].body).toEqual({ due_date: "2026-12-01" });
  });

  it("cancels a follow-up only after confirming", async () => {
    const { calls } = backend();
    const { user } = renderApp("/follow-ups", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Cancel follow-up" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel this follow-up?" });
    expect(callsTo(calls, "PATCH", "/follow-ups/f1")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Cancel follow-up" }));
    await screen.findByText("Follow-up cancelled");
    expect(callsTo(calls, "PATCH", "/follow-ups/f1")[0].body).toEqual({ status: "cancelled" });
  });
});
