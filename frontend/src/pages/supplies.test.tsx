import { screen } from "@testing-library/react";
import type { SupplyItem } from "../api/types";
import { todayIso } from "../lib/dates";
import { admin, page } from "../test/fixtures";
import { callsTo, mockApi, signedInAs } from "../test/http";
import { renderApp } from "../test/render";
import { readText } from "../lib/download";

const ors: SupplyItem = {
  id: "s1", name: "ORS sachets", unit: "sachets", low_stock_threshold: 50, target_level: 200, active: true,
  on_hand: 40, low: true, created_at: "2026-10-01", updated_at: "2026-10-01",
};

describe("supplies", () => {
  it("shows stock with a low-stock badge", async () => {
    mockApi({ ...signedInAs(admin), "GET /supplies": [200, [ors]] });
    renderApp("/supplies", { signedIn: true });
    expect(await screen.findByText("ORS sachets")).toBeInTheDocument();
    expect(screen.getByText("40 sachets on hand")).toBeInTheDocument();
    expect(screen.getByText("Low stock")).toBeInTheDocument();
  });

  it("records a distribution and shows the server's stock check", async () => {
    let posts = 0;
    const { calls } = mockApi({
      ...signedInAs(admin),
      "GET /supplies/s1": [200, ors],
      "GET /supplies/s1/movements": [200, page([])],
      "POST /supplies/s1/movements": () => (++posts === 1
        ? [201, { id: "m1" }]
        : [422, { detail: ["quantity: only 30 sachets in stock"] }]),
    });
    const { user } = renderApp("/supplies/s1", { signedIn: true });
    await user.selectOptions(await screen.findByLabelText("Type"), "distributed");
    await user.type(screen.getByLabelText("Quantity"), "10");
    await user.click(screen.getByRole("button", { name: "Record stock movement" }));
    expect(await screen.findByText("Stock movement recorded")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/supplies/s1/movements")[0].body).toEqual({
      kind: "distributed", quantity: 10, movement_date: todayIso(), note: null,
    });
    await user.type(screen.getByLabelText("Quantity"), "99");
    await user.click(screen.getByRole("button", { name: "Record stock movement" }));
    expect(await screen.findByText("quantity: only 30 sachets in stock")).toBeInTheDocument();
  });

  it("exports the request list as CSV", async () => {
    mockApi({ ...signedInAs(admin), "GET /supplies/request-list": [200, [{ ...ors, request_quantity: 160 }]] });
    const { user } = renderApp("/supplies/request-list", { signedIn: true });
    expect(await screen.findByText("160")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export CSV" }));
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls.at(-1)![0] as Blob;
    expect(await readText(blob)).toContain("ORS sachets,sachets,40,200,160");
  });
});
