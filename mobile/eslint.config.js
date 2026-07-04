// Flat ESLint config for the mobile app, built on the shared Expo ruleset.
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");
const globals = require("globals");

module.exports = defineConfig([
  expoConfig,
  {
    // Plain CommonJS Node scripts (verify-hook guards like
    // scripts/check-accent-as-text.js), not RN/Expo code.
    files: ["scripts/**/*.js"],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ["scripts/**/*.test.js"],
    languageOptions: {
      globals: { ...globals.node, ...globals.jest },
    },
  },
  {
    ignores: ["dist/*", ".expo/*", "node_modules/*", "coverage/*"],
  },
]);
