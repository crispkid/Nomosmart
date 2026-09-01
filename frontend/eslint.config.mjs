import nextVitals from "eslint-config-next/core-web-vitals";
import noUntranslatedVisibleText from "./eslint-rules/no-untranslated-visible-text.mjs";
import { visibleTextAllowlist } from "./src/i18n/visibleTextAllowlist.mjs";

const eslintConfig = [
  ...nextVitals,
  {
    ignores: [".next/**", ".next-dev/**", "node_modules/**", "coverage/**", "tests/fixtures/**"]
  },
  {
    files: ["src/**/*.{js,jsx,ts,tsx}"],
    plugins: {
      nomosmart: {
        rules: {
          "no-untranslated-visible-text": noUntranslatedVisibleText
        }
      }
    },
    rules: {
      "nomosmart/no-untranslated-visible-text": [
        "error",
        { allowlist: visibleTextAllowlist }
      ]
    }
  }
];

export default eslintConfig;
