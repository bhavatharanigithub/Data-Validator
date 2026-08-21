export function EvidenceCard({
  title,
  observed,
  expected,
  explanation,
}: {
  title: string;
  observed?: string | number | null;
  expected?: string | number | null;
  explanation?: string | null;
}) {
  return (
    <div className="sv-card p-4">
      <p className="sv-label">{title}</p>
      {observed != null ? <p className="mt-2 text-sm">Observed: {String(observed)}</p> : null}
      {expected != null ? <p className="text-sm text-slate-400">Baseline: {String(expected)}</p> : null}
      {explanation ? <p className="mt-2 text-sm text-slate-300">{explanation}</p> : null}
    </div>
  );
}
