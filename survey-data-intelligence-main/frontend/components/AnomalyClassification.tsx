export function AnomalyClassification({ value }: { value?: string | null }) {
  const label = (value ?? "INFORMATIONAL").replaceAll("_", " ");
  return (
    <span className="inline-flex rounded border border-inst-border bg-inst-muted px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-inst-navy">
      {label}
    </span>
  );
}
