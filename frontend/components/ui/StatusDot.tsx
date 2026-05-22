// A small glowing status dot. The halo is an inline box-shadow so the
// glow color always matches the tone.
type Tone = "online" | "busy" | "error" | "idle";

const TONE: Record<Tone, { color: string; pulse: boolean }> = {
  online: { color: "#34d399", pulse: false },
  busy: { color: "#fbbf24", pulse: true },
  error: { color: "#fb7185", pulse: false },
  idle: { color: "#8a9ca6", pulse: false },
};

export default function StatusDot({
  tone = "idle",
  size = 10,
  title,
}: {
  tone?: Tone;
  size?: number;
  title?: string;
}) {
  const t = TONE[tone];
  return (
    <span
      title={title}
      className={`inline-block rounded-full shrink-0 ${t.pulse ? "animate-pulse-glow" : ""}`}
      style={{
        width: size,
        height: size,
        background: t.color,
        boxShadow: `0 0 ${Math.round(size * 0.9)}px ${t.color}`,
      }}
    />
  );
}
