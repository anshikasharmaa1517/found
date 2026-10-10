import type { ReactNode } from "react";

/** Page title, one line on what the page is for, and the page's actions. */
export function PageHeader({
  title,
  description,
  actions,
  titleId,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  titleId?: string;
}) {
  return (
    <header className="page-header">
      <div>
        <h1 id={titleId}>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

/** Why a list is empty and what to do about it. */
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action && <div className="actions">{action}</div>}
    </div>
  );
}

/** Placeholder rows shaped like the list that is loading. */
export function SkeletonRows({ rows = 5, label }: { rows?: number; label: string }) {
  const widths = ["38%", "52%", "31%", "46%", "27%", "41%"];
  return (
    <div className="skeleton" role="status" aria-busy="true" aria-label={label}>
      <span className="visually-hidden">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-row" aria-hidden="true">
          <span className="skeleton-bar" style={{ width: widths[i % widths.length] }} />
          <span className="skeleton-bar" style={{ width: "12%", marginLeft: "auto" }} />
        </div>
      ))}
    </div>
  );
}

/** Inline spinner for buttons; keeps the label so the width does not jump. */
export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}
