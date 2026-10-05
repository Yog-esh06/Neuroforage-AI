import type { Config } from "tailwindcss";

/**
 * Semantic palette (dark-first intelligence console):
 *   violet  = AI / reasoning        cyan    = retrieval / data
 *   emerald = verified              amber   = review required
 *   red     = high risk             magenta = contradiction
 */
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0a0b0e", 900: "#0d0e12", 800: "#111318", 700: "#161920", 600: "#1c1f27", 500: "#252932", 400: "#343944" },
        paper: { DEFAULT: "#ece9e2", dim: "#b9b6ae", mute: "#8a8d96", faint: "#5d6069" },
        violet: { DEFAULT: "#8b7cf6", soft: "#8b7cf61f", line: "#8b7cf666" },
        cyan: { DEFAULT: "#2dd4e6", soft: "#2dd4e61a", line: "#2dd4e655" },
        emerald: { DEFAULT: "#34d399", soft: "#34d3991a", line: "#34d39955" },
        amber: { DEFAULT: "#f5b942", soft: "#f5b9421a", line: "#f5b94255" },
        magenta: { DEFAULT: "#e268d8", soft: "#e268d81a", line: "#e268d855" },
        danger: { DEFAULT: "#f2606b", soft: "#f2606b1a", line: "#f2606b55" },
      },
      fontFamily: {
        sans: ['"Segoe UI Variable"', '"Inter"', "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ['"Cascadia Code"', '"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: { sm: "3px", DEFAULT: "5px", md: "6px", lg: "8px" },
      fontSize: { "2xs": ["10px", "14px"], xs: ["11.5px", "16px"], sm: ["13px", "19px"] },
      keyframes: {
        scan: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(250%)" } },
        pulseDot: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
      },
      animation: { scan: "scan 1.6s linear infinite", pulseDot: "pulseDot 1.4s ease-in-out infinite" },
    },
  },
  plugins: [],
};

export default config;
