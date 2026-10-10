import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n/i18n";

type Props = {
  title: string;
  value?: ReactNode;
  note?: ReactNode;
  to?: string;
  tone?: "alert" | "gold";
  wide?: boolean;
  soon?: boolean;
  children?: ReactNode;
};

export function BentoCard({ title, value, note, to, tone, wide, soon, children }: Props) {
  const { t } = useI18n();
  const className = ["bento-card", tone && `tone-${tone}`, wide && "wide", soon && "soon"].filter(Boolean).join(" ");
  const body = (
    <>
      <h2 className="bento-title">{title}</h2>
      {value !== undefined && <p className="bento-value">{value}</p>}
      {note && <p className="bento-note">{note}</p>}
      {soon && <p className="bento-note">{t("common.comingSoon")}</p>}
      {children}
    </>
  );
  if (to && !soon) return <Link to={to} className={className}>{body}</Link>;
  return <section className={className} aria-disabled={soon || undefined}>{body}</section>;
}
