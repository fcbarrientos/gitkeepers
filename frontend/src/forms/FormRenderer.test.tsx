import { screen, within } from "@testing-library/react";
import type { FormDefinition } from "../api/types";
import { bpForm, childForm } from "../test/fixtures";
import { renderWithI18n } from "../test/render";
import { FormRenderer } from "./FormRenderer";

function field(name: string) {
  return document.querySelector(`[data-field="${name}"]`) as HTMLElement;
}

describe("FormRenderer", () => {
  it("renders number fields with their range and reports parsed numbers", async () => {
    const onChange = vi.fn();
    const { user } = renderWithI18n(<FormRenderer form={bpForm} values={{}} onChange={onChange} />);
    expect(within(field("bp_systolic")).getByText("Range 50–260")).toBeInTheDocument();
    await user.type(screen.getByLabelText("BP systolic (mmHg)"), "140");
    expect(onChange).toHaveBeenLastCalledWith("bp_systolic", 140);
  });

  it("never sends partial or invalid numbers", async () => {
    const onChange = vi.fn();
    const { user } = renderWithI18n(<FormRenderer form={bpForm} values={{}} onChange={onChange} />);
    await user.type(screen.getByLabelText("Weight (kg)"), "1,5");
    expect(onChange).toHaveBeenLastCalledWith("weight_kg", null);
    expect(within(field("weight_kg")).getByText("Enter a number")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Pulse (bpm)"), "7.5");
    expect(onChange).toHaveBeenLastCalledWith("pulse_bpm", null);
    expect(within(field("pulse_bpm")).getByText("Enter a whole number")).toBeInTheDocument();
  });

  it("uses a three-state control for yes/no fields", async () => {
    const onChange = vi.fn();
    const { user } = renderWithI18n(<FormRenderer form={bpForm} values={{ headache: true }} onChange={onChange} />);
    const group = screen.getByRole("group", { name: "Headache" });
    expect(within(group).getByRole("button", { name: "Yes" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(group).getByRole("button", { name: "No" }));
    expect(onChange).toHaveBeenLastCalledWith("headache", false);
    await user.click(within(group).getByRole("button", { name: "Not recorded" }));
    expect(onChange).toHaveBeenLastCalledWith("headache", null);
  });

  it("renders single and multiple choice fields", async () => {
    const onChange = vi.fn();
    const { user } = renderWithI18n(
      <FormRenderer form={childForm} values={{ vaccines_given: ["BCG"] }} onChange={onChange} />,
    );
    await user.click(screen.getByRole("radio", { name: "partial" }));
    expect(onChange).toHaveBeenLastCalledWith("breastfeeding", "partial");
    await user.click(screen.getByRole("checkbox", { name: "HepB" }));
    expect(onChange).toHaveBeenLastCalledWith("vaccines_given", ["BCG", "HepB"]);
    await user.click(screen.getByRole("checkbox", { name: "BCG" }));
    expect(onChange).toHaveBeenLastCalledWith("vaccines_given", null);
  });

  it("shows AI suggestions to accept or reject, without replacing typed values", async () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    const { user } = renderWithI18n(
      <FormRenderer form={bpForm} values={{ bp_systolic: 140 }} pending={{ bp_systolic: 150, headache: true }}
        onAccept={onAccept} onReject={onReject} />,
    );
    expect(within(field("bp_systolic")).getByText("AI suggests: 150")).toBeInTheDocument();
    expect(screen.getByLabelText("BP systolic (mmHg)")).toHaveValue("140");
    expect(within(field("headache")).getByText("AI")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept AI value for Headache" }));
    expect(onAccept).toHaveBeenCalledWith("headache");
    await user.click(screen.getByRole("button", { name: "Reject AI value for BP systolic (mmHg)" }));
    expect(onReject).toHaveBeenCalledWith("bp_systolic");
  });

  it("uses Filipino labels with an English fallback", () => {
    localStorage.setItem("gk.lang", "fil");
    const form: FormDefinition = { ...bpForm, fields: [
      ...bpForm.fields, { name: "extra", type: "boolean", label: { en: "English only" } },
    ] };
    renderWithI18n(<FormRenderer form={form} values={{}} />);
    expect(screen.getByLabelText("Timbang (kg)")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "English only" })).toBeInTheDocument();
  });

  it("shows final visits read-only with where each value came from", () => {
    renderWithI18n(
      <FormRenderer form={bpForm} values={{ bp_systolic: 150, bp_diastolic: 95 }} readOnly
        sources={{ bp_systolic: "ai_accepted", bp_diastolic: "manual" }} />,
    );
    expect(screen.getByLabelText("BP systolic (mmHg)")).toHaveAttribute("readonly");
    expect(within(field("bp_systolic")).getByText("AI accepted")).toBeInTheDocument();
    expect(within(field("bp_diastolic")).queryByText("Typed")).not.toBeInTheDocument();
  });
});
