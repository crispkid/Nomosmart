/** null means unknown, never an estimate based on elapsed time. */
export function UploadProgressBar({ label, percent }: { label: string; percent: number | null }) {
  const value = percent !== null && Number.isFinite(percent) ? Math.min(100, Math.max(0, Math.round(percent))) : null;
  return <>
    <div className={`upload-progress-track${value === null ? " indeterminate" : ""}`} aria-label={label} aria-valuemax={100} aria-valuemin={0} aria-valuenow={value ?? undefined} role="progressbar">
      <span style={value === null ? undefined : { width: `${value}%` }} />
    </div>
    <div className="upload-progress-meta"><span>{label}</span>{value !== null ? <strong>{value}%</strong> : null}</div>
  </>;
}
