import { screen, within } from "@testing-library/react";
import type { Referral, ReferralFlag } from "../api/types";
import { admin, bpForm, page, patient } from "../test/fixtures";
import { callsTo, mockApi, signedInAs } from "../test/http";
import { renderApp } from "../test/render";

const flag: ReferralFlag = {
  id: "fl1", visit_id: "v1", patient_id: "p1", patient_name: "Ana Dela Cruz", rule_id: "bp-severe",
  reason_en: "Very high blood pressure (180/110 or higher)", reason_fil: "Napakataas na presyon (180/110 o higit pa)",
  urgency: "urgent", status: "open", dismiss_note: null, created_at: "2026-10-10 08:00:00",
  form_type: "bp_followup", visit_date: "2026-10-10",
};
const referral: Referral = {
  id: "r1", patient_id: "p1", patient_name: "Ana Dela Cruz", birth_date: "1995-03-14", sex: "female",
  barangay: "San Roque", sitio: "Malinis", flag_id: "fl1", facility: "Rural Health Unit",
  reason: flag.reason_en, urgency: "urgent", notes: null, status: "issued", created_by: "u1",
  created_by_name: "Ada Admin", created_at: "2026-10-10 08:05:00", updated_at: "2026-10-10 08:05:00",
  visit: { id: "v1", form_type: "bp_followup", visit_date: "2026-10-10", values: { bp_systolic: 185, bp_diastolic: 112 } },
};

function backend() {
  return mockApi({
    ...signedInAs(admin),
    "GET /referral-flags": [200, [flag]],
    "GET /referral-flags/fl1": [200, flag],
    "POST /referral-flags/fl1/dismiss": [200, { ...flag, status: "dismissed" }],
    "GET /referrals": [200, page([referral])],
    "GET /referrals/r1": [200, referral],
    "POST /referrals": [201, referral],
    "GET /patients/p1": [200, patient],
    "GET /forms/bp_followup": [200, bpForm],
  });
}

describe("referrals", () => {
  it("turns a flag into a referral and shows the slip", async () => {
    const { calls } = backend();
    const { user } = renderApp("/referrals", { signedIn: true });
    await user.click(await screen.findByRole("link", { name: "Create referral" }));
    expect(await screen.findByLabelText("Reason for referral")).toHaveValue(flag.reason_en);
    await user.type(screen.getByLabelText("Receiving facility (RHU or hospital)"), "Rural Health Unit");
    await user.click(screen.getByRole("button", { name: "Save and view slip" }));
    expect(await screen.findByRole("heading", { name: "Referral slip" })).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/referrals")[0].body).toEqual({
      patient_id: "p1", flag_id: "fl1", facility: "Rural Health Unit", reason: flag.reason_en,
      urgency: "urgent", notes: null,
    });
    const findings = await screen.findByRole("table");
    expect(within(findings).getByText("BP systolic (mmHg)")).toBeInTheDocument();
    expect(within(findings).getByText("185")).toBeInTheDocument();
  });

  it("dismisses a flag only after confirming", async () => {
    const { calls } = backend();
    const { user } = renderApp("/referrals", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(callsTo(calls, "POST", "/referral-flags/fl1/dismiss")).toHaveLength(0);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Dismiss" }));
    expect(await screen.findByText("Flag dismissed")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/referral-flags/fl1/dismiss")).toHaveLength(1);
  });

  it("lists issued referrals", async () => {
    backend();
    const { user } = renderApp("/referrals", { signedIn: true });
    await user.click(await screen.findByRole("tab", { name: "Referrals" }));
    expect(await screen.findByText("Rural Health Unit")).toBeInTheDocument();
    expect(screen.getByText("Issued")).toBeInTheDocument();
  });
});
