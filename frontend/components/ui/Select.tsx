import { SelectHTMLAttributes } from "react";

export default function Select({
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`bg-surface border border-edge rounded-lg px-2 py-2 text-sm text-primary
        outline-none transition-colors focus:border-accent/60 ${className}`}
    >
      {children}
    </select>
  );
}
