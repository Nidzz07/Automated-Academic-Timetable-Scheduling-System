/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      // Self-hosted through @fontsource (src/main.tsx): serif headings, sans body, mono only for ids and codes
      fontFamily: {
        sans: ['"Source Sans 3"', "Segoe UI", "Roboto", "sans-serif"],
        serif: ['"Source Serif 4"', "Georgia", "serif"],
        mono: ['"Source Code Pro"', "Consolas", "monospace"],
      },
      // One type scale: 15 px is the floor (tables, secondary text), 16 px body, then headings
      fontSize: {
        xs: ["0.9375rem", { lineHeight: "1.4rem" }],
        sm: ["1rem", { lineHeight: "1.5rem" }],
        base: ["1.0625rem", { lineHeight: "1.65rem" }],
        lg: ["1.1875rem", { lineHeight: "1.65rem" }],
        xl: ["1.375rem", { lineHeight: "1.85rem" }],
        "2xl": ["1.75rem", { lineHeight: "2.2rem" }],
      },
    },
  },
  plugins: [],
}
