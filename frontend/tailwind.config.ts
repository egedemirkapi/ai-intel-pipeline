import type { Config } from "tailwindcss";

// ─── Refined Jarvis — design tokens ──────────────────────────────────
// A dark instrument-panel palette: a pure black-sea base lit by neon-aqua.
// The three text tokens (primary / secondary / muted) all clear WCAG AA
// on the `panel` surface. `accent` (aqua) is reserved for interactive
// elements + identity — it is NOT a body-text colour.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#03080f", // deepest — page background base
        panel: "#0a1420", // glass card surface
        surface: "#0f1d2c", // raised surface — inputs, nested blocks
        edge: "#1e3c4d", // calm cyan-teal hairline border
        "edge-strong": "#2b5266", // border in hover / focus context

        accent: "#00f0c0", // neon aqua — interactive + identity
        glow: "#00e5ff", // cyan — glow / rim light

        // text — all AA-legible on `panel`
        primary: "#e7eff3", // near-white — headings, key values
        secondary: "#aebfc8", // body text
        muted: "#8a9ca6", // meta, timestamps, captions

        // semantic — status + feedback
        success: "#34d399", // emerald
        warn: "#fbbf24", // amber
        error: "#fb7185", // rose
        info: "#38bdf8", // sky
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      // Fixed type scale — 11 / 12 / 13 / 14 / 16 / 20 / 28.
      fontSize: {
        "2xs": ["11px", { lineHeight: "14px", letterSpacing: "0.04em" }],
        xs: ["12px", { lineHeight: "17px" }],
        sm: ["13px", { lineHeight: "19px" }],
        base: ["14px", { lineHeight: "21px" }],
        md: ["16px", { lineHeight: "24px" }],
        lg: ["20px", { lineHeight: "26px", letterSpacing: "-0.005em" }],
        xl: ["28px", { lineHeight: "32px", letterSpacing: "-0.012em" }],
      },
      borderRadius: {
        card: "14px",
      },
      boxShadow: {
        glow: "0 0 18px -2px rgba(0,229,255,0.45)",
        "glow-soft": "0 0 24px -6px rgba(0,240,192,0.35)",
        elev: "0 12px 36px -18px rgba(0,0,0,0.9)",
        "elev-hero":
          "0 18px 50px -22px rgba(0,0,0,0.92), 0 0 40px -24px rgba(0,240,192,0.4)",
      },
      keyframes: {
        "pulse-glow": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
        "fade-rise": {
          "0%": { opacity: "0", transform: "translateY(7px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-glow": "pulse-glow 1.6s ease-in-out infinite",
        "fade-rise": "fade-rise 0.4s ease-out both",
      },
    },
  },
  plugins: [],
};
export default config;
