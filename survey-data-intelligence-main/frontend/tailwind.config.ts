import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        inst: {
          navy: "var(--sv-navy)",
          "navy-deep": "var(--sv-navy-deep)",
          blue: "var(--sv-blue)",
          "blue-hover": "var(--sv-blue-hover)",
          page: "var(--sv-page)",
          surface: "var(--sv-surface)",
          muted: "var(--sv-muted)",
          text: "var(--sv-text)",
          "text-secondary": "var(--sv-text-secondary)",
          border: "var(--sv-border)",
          success: "var(--sv-success)",
          warning: "var(--sv-warning)",
          critical: "var(--sv-critical)",
          info: "var(--sv-info)",
          saffron: "var(--sv-saffron)",
          green: "var(--sv-india-green)",
        },
      },
      fontFamily: {
        sans: ["Source Sans 3", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        display: ["Source Serif 4", "Georgia", "Times New Roman", "serif"],
      },
      boxShadow: {
        inst: "0 1px 2px rgba(15, 23, 42, 0.06), 0 8px 24px rgba(15, 36, 84, 0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
