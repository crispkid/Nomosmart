import type { ReactNode } from "react";

export function SettingsCard({ panel, title, description, children }: {
  panel: string; title?: string; description?: string; children: ReactNode;
}) {
  return <section className="settings-card" id={`settings-panel-${panel}`} tabIndex={-1} aria-labelledby={title ? `settings-title-${panel}` : undefined}>
    {title ? <header className="system-section-header"><div><h2 id={`settings-title-${panel}`}>{title}</h2>{description ? <p>{description}</p> : null}</div></header> : null}
    <div className="settings-card-content">{children}</div>
  </section>;
}


export function SettingsFieldRow({ htmlFor, label, help, extra, children }: {
  htmlFor: string; label: ReactNode; help: ReactNode; extra?: ReactNode; children: ReactNode;
}) {
  return <div className="settings-field-row"><div><label htmlFor={htmlFor}>{label}</label><p id={`${htmlFor}-help`}>{help}</p>{extra}</div><div className="settings-field-control">{children}</div></div>;
}
