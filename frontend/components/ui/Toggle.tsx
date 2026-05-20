// Accessible on/off switch with a glowing knob when active.
export default function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2 text-sm text-slate-300"
    >
      <span
        className={`relative h-5 w-9 rounded-full transition-colors ${
          checked
            ? "bg-accent/25 border border-accent/60"
            : "bg-ink border border-edge"
        }`}
      >
        <span
          className={`absolute top-[3px] h-3.5 w-3.5 rounded-full transition-all ${
            checked ? "left-[18px] bg-accent shadow-glow" : "left-[3px] bg-slate-500"
          }`}
        />
      </span>
      {label && <span>{label}</span>}
    </button>
  );
}
