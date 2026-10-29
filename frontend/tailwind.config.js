/** Design tokens from the foundation doc: warm paper, deep lagoon teal, one terracotta accent, sand dividers. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FAF7F2",
        surface: "#FFFFFF",
        ink: { DEFAULT: "#16241F", soft: "#4A5A54", faint: "#7C8A84" },
        lagoon: { DEFAULT: "#0F5C5A", dark: "#0A4543", tint: "#E6F0EF" },
        terracotta: { DEFAULT: "#C8553D", dark: "#A94430", tint: "#F8E9E4" },
        sand: { DEFAULT: "#E9DFCF", dark: "#D6C9B2", light: "#F3EDE2" },
        olive: { DEFAULT: "#5F6E2F", tint: "#EEF1E1" },
        amber: { DEFAULT: "#A86A12", tint: "#FBF0DC" },
      },
      fontFamily: {
        display: ["Fraunces", "Iowan Old Style", "Georgia", "serif"],
        sans: ["Figtree", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      borderRadius: { sm: "5px", DEFAULT: "8px", md: "8px", lg: "10px" },
      boxShadow: { pop: "0 8px 24px -8px rgba(22,36,31,0.25)" },
      keyframes: {
        rise: { "0%": { opacity: "0", transform: "translateY(4px)" }, "100%": { opacity: "1", transform: "none" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
      },
      animation: { rise: "rise .18s ease-out both", shimmer: "shimmer 1.6s linear infinite" },
    },
  },
  plugins: [],
};
