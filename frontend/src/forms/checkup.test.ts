import { addDays, todayIso } from "../lib/dates";
import { acceptedFrom, checkupReducer, emptyCheckup, savedFields, type CheckupAction, type CheckupState } from "./checkup";

const run = (...actions: CheckupAction[]): CheckupState => actions.reduce(checkupReducer, emptyCheckup);
const suggested = (values: Record<string, unknown>): CheckupAction =>
  ({ type: "suggested", suggestionId: "s1", values } as CheckupAction);

describe("checkup reducer", () => {
  it("holds suggestions for review without changing the form", () => {
    const state = run(suggested({ bp_systolic: 150, headache: true, pulse_bpm: null }));
    expect(state.pending).toEqual({ bp_systolic: 150, headache: true });
    expect(state.values).toEqual({});
    expect(state.dirty).toBe(false);
  });

  it("accepting copies the value and records it as accepted", () => {
    const state = run(suggested({ bp_systolic: 150 }), { type: "accept", name: "bp_systolic" });
    expect(state.values.bp_systolic).toBe(150);
    expect(state.accepted).toEqual(["bp_systolic"]);
    expect(state.pending).toEqual({});
    expect(state.dirty).toBe(true);
  });

  it("never overwrites a value the worker typed", () => {
    const state = run(
      { type: "set", name: "bp_systolic", value: 140 },
      suggested({ bp_systolic: 150, headache: true }),
      { type: "acceptAll" },
    );
    expect(state.values).toEqual({ bp_systolic: 140, headache: true });
    expect(state.accepted).toEqual(["headache"]);
    expect(state.pending).toEqual({ bp_systolic: 150 });
  });

  it("rejecting drops the suggestion", () => {
    const state = run(suggested({ headache: true }), { type: "reject", name: "headache" });
    expect(state.pending).toEqual({});
    expect(state.values).toEqual({});
  });

  it("clearing an accepted field forgets that it came from the AI", () => {
    const state = run(suggested({ headache: true }), { type: "accept", name: "headache" },
      { type: "set", name: "headache", value: null });
    expect(state.accepted).toEqual([]);
  });

  it("a new suggestion keeps provenance only for fields it suggests again", () => {
    const state = run(
      suggested({ bp_systolic: 150, headache: true }), { type: "acceptAll" },
      { type: "suggested", suggestionId: "s2", values: { bp_systolic: 150, headache: null } },
    );
    expect(state.suggestionId).toBe("s2");
    expect(state.accepted).toEqual(["bp_systolic"]);
    expect(state.pending).toEqual({}); // 150 already matches the form
  });

  it("builds the save fields", () => {
    const state = run(
      { type: "set", name: "pulse_bpm", value: 80 },
      { type: "set", name: "weight_kg", value: null },
      suggested({ headache: true }), { type: "accept", name: "headache" },
    );
    expect(savedFields(state)).toEqual({
      values: { pulse_bpm: 80, headache: true }, suggestion_id: "s1", ai_accepted_fields: ["headache"],
    });
  });

  it("loads a saved draft's AI provenance", () => {
    expect(acceptedFrom({ a: "ai_accepted", b: "ai_edited", c: "manual" })).toEqual(["a", "b"]);
    const state = run({ type: "load", values: { a: 1, b: null }, suggestionId: "s9", accepted: ["a"] });
    expect(state).toEqual({ values: { a: 1 }, pending: {}, suggestionId: "s9", accepted: ["a"], dirty: false });
  });
});

describe("dates", () => {
  it("formats today in local time and adds days across month and year ends", () => {
    expect(todayIso(new Date(2026, 9, 10, 23, 30))).toBe("2026-10-10");
    expect(addDays("2026-10-10", 30)).toBe("2026-11-09");
    expect(addDays("2026-12-20", 28)).toBe("2027-01-17");
  });
});
