import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent/15 text-accent border border-accent/40 hover:bg-accent/25 hover:shadow-glow-soft",
  ghost:
    "bg-transparent text-secondary border border-edge hover:border-glow/50 hover:text-glow",
  danger:
    "bg-error/10 text-error border border-error/40 hover:bg-error/20",
};

export default function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...props}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-all
        disabled:opacity-40 disabled:pointer-events-none ${VARIANTS[variant]} ${className}`}
    />
  );
}
