import { useEffect, useState } from "react";
import type { FieldValue, FormDefinition, FormField, Source, Values } from "../api/types";
import { pick, useI18n, type Translate } from "../i18n/i18n";
import { isEmpty, sameValue } from "./checkup";

type Props = {
  form: FormDefinition;
  values: Values;
  pending?: Values;
  errors?: Record<string, string>;
  sources?: Record<string, Source>;
  readOnly?: boolean;
  onChange?: (name: string, value: FieldValue) => void;
  onAccept?: (name: string) => void;
  onReject?: (name: string) => void;
  /** Called when a field starts or stops holding text that is not a valid value. */
  onInvalid?: (name: string, invalid: boolean) => void;
};

export function FormRenderer({ form, values, pending = {}, errors = {}, sources = {}, readOnly = false, onChange, onAccept, onReject, onInvalid }: Props) {
  return (
    <div className="form-grid">
      {form.fields.map((field) => (
        <FieldBlock
          key={field.name}
          field={field}
          value={values[field.name] ?? null}
          suggestion={field.name in pending ? pending[field.name] : undefined}
          error={errors[field.name]}
          source={sources[field.name]}
          readOnly={readOnly}
          onChange={(value) => onChange?.(field.name, value)}
          onAccept={() => onAccept?.(field.name)}
          onReject={() => onReject?.(field.name)}
          onInvalid={(invalid) => onInvalid?.(field.name, invalid)}
        />
      ))}
    </div>
  );
}

export function ProvenanceBadge({ source }: { source: Source }) {
  const { t } = useI18n();
  return <span className={`badge badge-${source}`}>{t(`provenance.${source}`)}</span>;
}

export function displayValue(value: FieldValue, t: Translate): string {
  if (value === true) return t("form.yes");
  if (value === false) return t("form.no");
  if (Array.isArray(value)) return value.join(", ");
  return value === null ? "" : String(value);
}

/** null for empty text, a number for valid text, undefined for text that is not a number yet. */
export function parseNumber(text: string, integer: boolean): number | null | undefined {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  return (integer ? /^-?\d+$/ : /^-?\d+(\.\d+)?$/).test(trimmed) ? Number(trimmed) : undefined;
}

type BlockProps = {
  field: FormField;
  value: FieldValue;
  suggestion: FieldValue | undefined;
  error?: string;
  source?: Source;
  readOnly: boolean;
  onChange: (value: FieldValue) => void;
  onAccept: () => void;
  onReject: () => void;
  onInvalid: (invalid: boolean) => void;
};

function FieldBlock({ field, value, suggestion, error, source, readOnly, onChange, onAccept, onReject, onInvalid }: BlockProps) {
  const { t, lang } = useI18n();
  const [localError, setLocalError] = useState<string | null>(null);
  const reportInvalid = (message: string | null) => {
    setLocalError(message);
    onInvalid(message !== null);
  };
  const label = pick(field.label, lang);
  const id = `field-${field.name}`;
  const labelId = `${id}-label`;
  const numeric = field.type === "integer" || field.type === "number";
  const hasSuggestion = suggestion !== undefined;
  const conflict = hasSuggestion && !isEmpty(value) && !sameValue(value, suggestion);
  const shownError = localError ?? error;
  return (
    <div className={["field", hasSuggestion && "field-ai", shownError && "field-error"].filter(Boolean).join(" ")} data-field={field.name}>
      <div className="field-label">
        {numeric ? <label id={labelId} htmlFor={id}>{label}</label> : <span id={labelId}>{label}</span>}
        {field.required && <span className="required" title={t("form.required")}>*</span>}
        {source && source !== "manual" && <ProvenanceBadge source={source} />}
      </div>
      <FieldInput field={field} id={id} labelId={labelId} value={value} readOnly={readOnly} onChange={onChange} onInvalid={reportInvalid} />
      {numeric && field.min != null && field.max != null && (
        <p className="hint">{t("form.range", { min: field.min, max: field.max })}</p>
      )}
      {hasSuggestion && (
        <div className="ai-suggestion">
          <span className="ai-tag">AI</span>
          <span className="ai-value">
            {conflict ? t("form.aiSuggests", { value: displayValue(suggestion, t) }) : displayValue(suggestion, t)}
          </span>
          <button type="button" className="btn btn-small" aria-label={t("form.acceptField", { field: label })} onClick={onAccept}>✓</button>
          <button type="button" className="btn btn-small" aria-label={t("form.rejectField", { field: label })} onClick={onReject}>✕</button>
        </div>
      )}
      {shownError && <p className="error-text" role="alert">{shownError}</p>}
    </div>
  );
}

type InputProps = {
  field: FormField;
  id: string;
  labelId: string;
  value: FieldValue;
  readOnly: boolean;
  onChange: (value: FieldValue) => void;
  onInvalid: (message: string | null) => void;
};

function FieldInput(props: InputProps) {
  switch (props.field.type) {
    case "integer":
    case "number":
      return <NumberInput {...props} />;
    case "boolean":
      return <BooleanInput {...props} />;
    case "choice":
      return <ChoiceInput {...props} />;
    case "choices":
      return <ChoicesInput {...props} />;
  }
}

function NumberInput({ field, id, value, readOnly, onChange, onInvalid }: InputProps) {
  const { t } = useI18n();
  const integer = field.type === "integer";
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => {
    // Follow changes made outside this input, such as an accepted AI value.
    const parsed = parseNumber(text, integer);
    if (parsed === undefined ? value !== null : parsed !== value) {
      setText(value === null ? "" : String(value));
      onInvalid(null);
    }
  }, [value]);
  return (
    <input
      id={id}
      type="text"
      inputMode={integer ? "numeric" : "decimal"}
      autoComplete="off"
      value={text}
      readOnly={readOnly}
      onChange={(event) => {
        const next = event.target.value;
        setText(next);
        const parsed = parseNumber(next, integer);
        onInvalid(parsed === undefined ? t(integer ? "form.enterWholeNumber" : "form.enterNumber") : null);
        onChange(parsed === undefined ? null : parsed);
      }}
    />
  );
}

const YES_NO: [boolean | null, string][] = [[true, "form.yes"], [false, "form.no"], [null, "form.notRecorded"]];

function BooleanInput({ labelId, value, readOnly, onChange }: InputProps) {
  const { t } = useI18n();
  return (
    <div className="segmented" role="group" aria-labelledby={labelId}>
      {YES_NO.map(([option, key]) => (
        <button key={key} type="button" aria-pressed={value === option} disabled={readOnly} onClick={() => onChange(option)}>
          {t(key)}
        </button>
      ))}
    </div>
  );
}

function ChoiceInput({ field, id, labelId, value, readOnly, onChange }: InputProps) {
  const { t } = useI18n();
  return (
    <div className="choices" role="radiogroup" aria-labelledby={labelId}>
      {[...(field.options ?? []), null].map((option) => (
        <label key={option ?? "none"} className="check">
          <input type="radio" name={id} checked={value === option} disabled={readOnly} onChange={() => onChange(option)} />
          {option ?? t("form.notRecorded")}
        </label>
      ))}
    </div>
  );
}

function ChoicesInput({ field, labelId, value, readOnly, onChange }: InputProps) {
  const options = field.options ?? [];
  const selected = Array.isArray(value) ? value : [];
  const toggle = (option: string, on: boolean) => {
    const next = options.filter((o) => (o === option ? on : selected.includes(o)));
    onChange(next.length ? next : null);
  };
  return (
    <div className="choices" role="group" aria-labelledby={labelId}>
      {options.map((option) => (
        <label key={option} className="check">
          <input type="checkbox" checked={selected.includes(option)} disabled={readOnly}
            onChange={(event) => toggle(option, event.target.checked)} />
          {option}
        </label>
      ))}
    </div>
  );
}
