import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { emptyMember, MemberFields, memberInput, type MemberDraft } from "../components/MemberFields";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function HouseholdPage() {
  const { householdId = "" } = useParams();
  const { t } = useI18n();
  const toast = useToast();
  const household = useApi(() => api.getHousehold(householdId), [householdId]);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<MemberDraft>(emptyMember);

  async function addMember(event: FormEvent) {
    event.preventDefault();
    try {
      await api.addMember(householdId, memberInput(draft));
      toast(t("households.memberAdded"));
      setAdding(false);
      setDraft(emptyMember);
      household.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  if (household.error) return <LoadError error={household.error} onRetry={household.reload} />;
  if (!household.data) return <Loading />;
  const h = household.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{[h.sitio, h.barangay].filter(Boolean).join(", ")}</h1>
          <p className="muted">{[h.address_line, h.contact_number].filter(Boolean).join(" · ")}</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>{t("households.addMember")}</button>
      </div>
      {adding && (
        <form className="card" onSubmit={addMember}>
          <MemberFields value={draft} onChange={setDraft} />
          <div className="actions">
            <button type="button" className="btn" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("common.save")}</button>
          </div>
        </form>
      )}
      <h2>{t("households.membersTitle")}</h2>
      <ul className="list">
        {h.members.map((m) => (
          <li key={m.id}>
            <Link to={`/patients/${m.id}`} className="list-row">
              <strong>{m.full_name}</strong>
              {m.is_household_head && <span className="badge">{t("member.head")}</span>}
              {m.birth_date && <span className="muted">{t("patients.born", { date: m.birth_date })}</span>}
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
