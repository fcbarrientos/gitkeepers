import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { emptyMember, MemberFields, memberInput, type MemberDraft } from "../components/MemberFields";
import { errorText } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function HouseholdNewPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [place, setPlace] = useState({ barangay: "", sitio: "", address_line: "", contact_number: "" });
  const [members, setMembers] = useState<MemberDraft[]>([{ ...emptyMember, is_household_head: true }]);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setErrors([]);
    try {
      const created = await api.createHousehold({
        barangay: place.barangay.trim(),
        sitio: place.sitio.trim() || null,
        address_line: place.address_line.trim() || null,
        contact_number: place.contact_number.trim() || null,
        members: members.filter((m) => m.full_name.trim()).map(memberInput),
      });
      navigate(`/households/${created.id}`, { replace: true });
    } catch (failure) {
      setErrors(failure instanceof ApiError ? failure.messages : [errorText(failure, t)]);
      setBusy(false);
    }
  }

  const setPlaceField = (key: keyof typeof place) => ({
    value: place[key],
    onChange: (e: ChangeEvent<HTMLInputElement>) => setPlace({ ...place, [key]: e.target.value }),
  });

  return (
    <form onSubmit={submit}>
      <div className="page-head"><h1>{t("households.register")}</h1></div>
      <section className="card">
        <h2>{t("households.place")}</h2>
        <div className="inline-fields">
          <label className="stack">{t("households.barangay")}<input required {...setPlaceField("barangay")} /></label>
          <label className="stack">{t("households.sitio")}<input {...setPlaceField("sitio")} /></label>
          <label className="stack">{t("households.address")}<input {...setPlaceField("address_line")} /></label>
          <label className="stack">{t("households.contact")}<input inputMode="tel" {...setPlaceField("contact_number")} /></label>
        </div>
      </section>
      <h2>{t("households.membersTitle")}</h2>
      {members.map((member, index) => (
        <fieldset key={index} className="card">
          <legend>{t("households.memberN", { n: index + 1 })}</legend>
          <MemberFields value={member} onChange={(next) => setMembers(members.map((m, i) => (i === index ? next : m)))} />
          {members.length > 1 && (
            <button type="button" className="btn btn-small" onClick={() => setMembers(members.filter((_, i) => i !== index))}>
              {t("households.remove")}
            </button>
          )}
        </fieldset>
      ))}
      <button type="button" className="btn" onClick={() => setMembers([...members, { ...emptyMember }])}>
        {t("households.addAnother")}
      </button>
      {errors.length > 0 && (
        <div className="notice notice-error" role="alert">{errors.map((m) => <p key={m}>{m}</p>)}</div>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>{t("households.register")}</button>
      </div>
    </form>
  );
}
