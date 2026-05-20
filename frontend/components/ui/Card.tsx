import { ReactNode } from "react";

// Glass panel with an optional glowing header. Replaces the repeated
// `bg-panel border border-edge rounded-xl` section markup.
export default function Card({
  title,
  right,
  className = "",
  children,
}: {
  title?: string;
  right?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`glass rounded-xl p-4 flex flex-col ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between mb-3 shrink-0">
          {title && (
            <h2 className="text-[13px] font-semibold tracking-[0.16em] text-accent glow-aqua">
              {title}
            </h2>
          )}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}
