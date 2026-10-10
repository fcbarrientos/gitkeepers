import type { FieldValue, Source, Values } from "../api/types";

/**
 * Checkup form state. `pending` holds AI suggestions the worker has not accepted or rejected.
 * `accepted` lists fields whose value came from the AI; the backend marks them ai_accepted or,
 * when the saved value differs from the suggestion, ai_edited.
 */
export type CheckupState = {
  values: Values;
  pending: Values;
  suggestionId: string | null;
  accepted: string[];
  dirty: boolean;
};

export type CheckupAction =
  | { type: "load"; values: Values; suggestionId: string | null; accepted: string[] }
  | { type: "set"; name: string; value: FieldValue }
  | { type: "suggested"; suggestionId: string; values: Values }
  | { type: "accept"; name: string }
  | { type: "reject"; name: string }
  | { type: "acceptAll" }
  | { type: "saved" };

export const emptyCheckup: CheckupState = { values: {}, pending: {}, suggestionId: null, accepted: [], dirty: false };

export function isEmpty(value: FieldValue | undefined): boolean {
  return value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0);
}

export function sameValue(a: FieldValue | undefined, b: FieldValue | undefined): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && [...a].sort().join("\n") === [...b].sort().join("\n");
  return a === b;
}

export function compact(values: Values): Values {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => !isEmpty(value)));
}

export function acceptedFrom(sources: Record<string, Source>): string[] {
  return Object.keys(sources).filter((name) => sources[name] !== "manual");
}

function without(record: Values, name: string): Values {
  const copy = { ...record };
  delete copy[name];
  return copy;
}

function accept(state: CheckupState, name: string): CheckupState {
  if (!(name in state.pending)) return state;
  return {
    ...state,
    values: { ...state.values, [name]: state.pending[name] },
    pending: without(state.pending, name),
    accepted: state.accepted.includes(name) ? state.accepted : [...state.accepted, name],
    dirty: true,
  };
}

export function checkupReducer(state: CheckupState, action: CheckupAction): CheckupState {
  switch (action.type) {
    case "load":
      return { values: compact(action.values), pending: {}, suggestionId: action.suggestionId, accepted: action.accepted, dirty: false };
    case "set": {
      const accepted = isEmpty(action.value) ? state.accepted.filter((name) => name !== action.name) : state.accepted;
      return { ...state, values: { ...state.values, [action.name]: action.value }, accepted, dirty: true };
    }
    case "suggested": {
      const suggested = compact(action.values);
      const pending = Object.fromEntries(
        Object.entries(suggested).filter(([name, value]) => !sameValue(state.values[name], value)),
      );
      return {
        ...state,
        pending,
        suggestionId: action.suggestionId,
        accepted: state.accepted.filter((name) => name in suggested),
      };
    }
    case "accept":
      return accept(state, action.name);
    case "reject":
      return { ...state, pending: without(state.pending, action.name) };
    case "acceptAll":
      return Object.keys(state.pending)
        .filter((name) => isEmpty(state.values[name]))
        .reduce(accept, state);
    case "saved":
      return { ...state, dirty: false };
  }
}

/** The parts of a visit request that come from the form state. */
export function savedFields(state: CheckupState) {
  const values = compact(state.values);
  return {
    values,
    suggestion_id: state.suggestionId,
    ai_accepted_fields: state.accepted.filter((name) => name in values),
  };
}
