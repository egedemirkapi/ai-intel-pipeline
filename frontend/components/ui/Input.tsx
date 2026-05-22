import { InputHTMLAttributes } from "react";

export default function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`bg-surface border border-edge rounded-lg px-3 py-2 text-sm text-primary
        outline-none transition-colors placeholder:text-muted
        focus:border-accent/60 focus:shadow-glow-soft ${className}`}
    />
  );
}
