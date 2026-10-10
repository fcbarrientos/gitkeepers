import type { MemberInput, Sex } from "../api/types";
import { useI18n } from "../i18n/i18n";

export type MemberDraft = {
  full_name: string;
  sex: string;
  birth_date: string;
  contact_number: string;
  relationship_to_head: string;
  is_household_head: boolean;
};

export const emptyMember: MemberDraft = {
  full_name: "", sex: "", birth_date: "", contact_number: "", relationship_to_head: "", is_household_head: false,
};

const SEXES: Sex[] = ["female", "male", "intersex", "unknown"];

export function memberInput(draft: MemberDraft): MemberInput {
  return {
    full_name: draft.full_name.trim(),
    sex: (draft.sex || null) as Sex | null,
    birth_date: draft.birth_date || null,
    contact_number: draft.contact_number.trim() || null,
    relationship_to_head: draft.relationship_to_head.trim() || null,
    is_household_head: draft.is_household_head,
  };
}

export function MemberFields({ value, onChange }: { value: MemberDraft; onChange: (next: MemberDraft) => void }) {
  const { t } = useI18n();
  const set = <K extends keyof MemberDraft>(key: K, next: MemberDraft[K]) => onChange({ ...value, [key]: next });
  return (
    <div className="member-fields">
      <label className="stack">{t("member.fullName")}
        <input required value={value.full_name} onChange={(e) => set("full_name", e.target.value)} />
      </label>
      <label className="stack">{t("member.sex")}
        <select value={value.sex} onChange={(e) => set("sex", e.target.value)}>
          <option value="">{t("member.sex.unset")}</option>
          {SEXES.map((sex) => <option key={sex} value={sex}>{t(`member.sex.${sex}`)}</option>)}
        </select>
      </label>
      <label className="stack">{t("member.birthDate")}
        <input type="date" value={value.birth_date} onChange={(e) => set("birth_date", e.target.value)} />
      </label>
      <label className="stack">{t("member.contact")}
        <input inputMode="tel" value={value.contact_number} onChange={(e) => set("contact_number", e.target.value)} />
      </label>
      <label className="stack">{t("member.relationship")}
        <input value={value.relationship_to_head} onChange={(e) => set("relationship_to_head", e.target.value)} />
      </label>
      <label className="check">
        <input type="checkbox" checked={value.is_household_head} onChange={(e) => set("is_household_head", e.target.checked)} />
        {t("member.isHead")}
      </label>
    </div>
  );
}
