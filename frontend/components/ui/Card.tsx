import { ReactNode } from "react";

// Glass panel with an optional section-label header.
// `hero` swaps the standard surface for the accent-tinted, elevated
// hero treatment — reserved for the one panel that should lead the eye.
export default function Card({
  title,
  right,
  hero = false,
  className = "",
  children,
}: {
  title?: string;
  right?: ReactNode;
  hero?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={`${hero ? "glass-hero" : "glass"} rounded-card p-4 flex flex-col ${className}`}
    >
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 mb-3 shrink-0">
          {title && (
            <h2 className={`label ${hero ? "text-accent glow-aqua" : "text-glow/70"}`}>
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
