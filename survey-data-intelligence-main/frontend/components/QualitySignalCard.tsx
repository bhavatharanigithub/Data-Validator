export function QualitySignalCard({
  label,
  value,
  max,
  onClick,
}: {
  label: string;
  value: number | string;
  max?: number;
  onClick?: () => void;
}) {
  const numeric = typeof value === "number" ? value : null;
  const width = numeric != null && max && max > 0 ? Math.min(100, (numeric / max) * 100) : 0;
  return (
    <button type="button" onClick={onClick} className="sv-card p-4 text-left hover:border-inst-blue">
      <p className="sv-label">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-inst-navy">{value}</p>
      {numeric != null ? (
        <div className="sv-bar mt-3" aria-hidden="true">
          <span className="bg-inst-blue" style={{ width: `${width}%` }} />
        </div>
      ) : null}
    </button>
  );
}
