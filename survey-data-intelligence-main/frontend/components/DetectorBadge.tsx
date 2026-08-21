export function DetectorBadge({ value }: { value?: string | null }) {
  if (!value) return <span className="text-inst-text-secondary">—</span>;
  const label = value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
  return <span className="sv-chip">{label}</span>;
}
