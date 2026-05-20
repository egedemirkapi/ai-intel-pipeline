import type { Config } from "tailwindcss";

// Bioluminescent palette — a pure black-sea base lit by neon-aqua.
// `ink/panel/edge` keep their names so existing classes recolor for free.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#03080f",     // deepest — page background base
        panel: "#0a1420",   // glass card surface
        edge: "#15394a",    // calm cyan-teal border
        accent: "#00f0c0",  // neon aqua — primary accent
        glow: "#00e5ff",    // cyan — glow / rim light
      },
      boxShadow: {
        glow: "0 0 18px -2px rgba(0,229,255,0.45)",
        "glow-soft": "0 0 24px -6px rgba(0,240,192,0.35)",
      },
      keyframes: {
        "pulse-glow": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
      },
      animation: {
        "pulse-glow": "pulse-glow 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
