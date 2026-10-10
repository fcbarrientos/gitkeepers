import { screen, within } from "@testing-library/react";
import type { SyncStatus } from "../api/types";
import { admin, volunteer } from "../test/fixtures";
import { callsTo, mockApi, signedInAs, type Route } from "../test/http";
import { renderApp } from "../test/render";
import { readText } from "../lib/download";

const counts = (pending: number, awaiting = 0, synced = 0) => ({ pending, awaiting, synced });
const status: SyncStatus = {
  station_id: "station-ab12cd34", passphrase_set: true, last_acknowledged_at: null, open_bundles: 1,
  records: { household: counts(1), patient: counts(2), visit: counts(3, 1), follow_up: counts(0),
    referral: counts(1), supply_item: counts(0), supply_movement: counts(0) },
};
const openBundle = { id: "b1", record_count: 4, created_at: "2026-10-10 08:00:00", acknowledged_at: null, created_by_name: "Ada Admin" };

function backend(user = admin, extra: Record<string, Route> = {}) {
  return mockApi({
    ...signedInAs(user),
    "GET /sync/status": [200, status],
    "GET /sync/bundles": [200, [openBundle]],
    "POST /sync/bundles": [201, { bundle_id: "b2", station_id: "station-ab12cd34", record_count: 7, payload: [] }],
    ...extra,
  });
}

describe("sync", () => {
  it("creates and downloads a transfer file", async () => {
    const { calls } = backend();
    const { user } = renderApp("/sync", { signedIn: true });
    expect(await screen.findByText("Finalized visits")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create transfer file" }));
    expect(await screen.findByText("Transfer file created with 7 records. Give it to the RHU.")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/sync/bundles")).toHaveLength(1);
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls.at(-1)![0] as Blob;
    expect(JSON.parse(await readText(blob)).bundle_id).toBe("b2");
  });

  it("imports a receipt and shows a clear error for a bad one", async () => {
    let attempt = 0;
    const { calls } = backend(admin, {
      "POST /sync/receipts": () => (++attempt === 1
        ? [422, { detail: ["signature: this receipt was not signed with this device's RHU passphrase"] }]
        : [200, { ...openBundle, acknowledged_at: "2026-10-10 09:00:00" }]),
    });
    const { user } = renderApp("/sync", { signedIn: true });
    const input = await screen.findByLabelText("Receipt file from the RHU");
    const receipt = { format: "gitkeepers-receipt-v1", bundle_id: "b1", record_count: 4, signature: "x" };
    await user.upload(input, new File([JSON.stringify(receipt)], "r.json", { type: "application/json" }));
    expect(await screen.findByText("signature: this receipt was not signed with this device's RHU passphrase"))
      .toBeInTheDocument();
    await user.upload(input, new File([JSON.stringify(receipt)], "r.json", { type: "application/json" }));
    expect(await screen.findByText("Receipt accepted: records marked as synced")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/sync/receipts")[1].body).toEqual(receipt);
    await user.upload(input, new File(["not json"], "r.json", { type: "application/json" }));
    expect(await screen.findByText("This file is not a receipt (not valid JSON).")).toBeInTheDocument();
  });

  it("cancels a transfer file only after confirming", async () => {
    const { calls } = backend(admin, { "POST /sync/bundles/b1/cancel": [204] });
    const { user } = renderApp("/sync", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Cancel file" }));
    expect(callsTo(calls, "POST", "/sync/bundles/b1/cancel")).toHaveLength(0);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel file" }));
    expect(await screen.findByText("Transfer file cancelled: its records are waiting to transfer again")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/sync/bundles/b1/cancel")).toHaveLength(1);
  });

  it("shows volunteers the status but not the admin actions", async () => {
    backend(volunteer);
    renderApp("/sync", { signedIn: true });
    expect(await screen.findByText("Only an admin can create transfer files and import receipts.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create transfer file" })).not.toBeInTheDocument();
  });
});
