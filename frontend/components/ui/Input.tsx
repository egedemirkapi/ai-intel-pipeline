import { InputHTMLAttributes } from "react";

export default function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`bg-ink/70 border border-edge rounded-lg px-3 py-2 text-sm text-slate-100
        outline-none transition-colors placeholder:text-slate-600
        focus:border-accent/60 focus:shadow-glow-soft ${className}`}
    />
  );
}
