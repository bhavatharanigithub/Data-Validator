export function InstitutionalMark({ className = "h-16 w-16" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 64 64"
      role="img"
      aria-label="Survey Data Intelligence mark"
    >
      <circle cx="32" cy="32" r="31" fill="#163a6e" />
      <circle cx="32" cy="32" r="26" fill="none" stroke="#d7dee8" strokeWidth="1.25" />
      <circle cx="32" cy="32" r="10" fill="none" stroke="#c45c26" strokeWidth="1.5" />
      {Array.from({ length: 24 }, (_, index) => {
        const angle = (index * Math.PI) / 12;
        const inner = 11;
        const outer = 22;
        const x1 = 32 + Math.cos(angle) * inner;
        const y1 = 32 + Math.sin(angle) * inner;
        const x2 = 32 + Math.cos(angle) * outer;
        const y2 = 32 + Math.sin(angle) * outer;
        return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#e8eef5" strokeWidth="1.1" />;
      })}
      <circle cx="32" cy="32" r="3.2" fill="#1f6b4a" />
    </svg>
  );
}
