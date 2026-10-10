import { useState, type FormEvent } from "react";
import { useI18n } from "../i18n/i18n";

export function SearchBox({ value, label, onSearch }: { value: string; label: string; onSearch: (text: string) => void }) {
  const { t } = useI18n();
  const [text, setText] = useState(value);
  function submit(event: FormEvent) {
    event.preventDefault();
    onSearch(text.trim());
  }
  return (
    <form role="search" className="search" onSubmit={submit}>
      <input type="search" aria-label={label} placeholder={label} value={text} onChange={(e) => setText(e.target.value)} />
      <button type="submit" className="btn">{t("common.search")}</button>
    </form>
  );
}
