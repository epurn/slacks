// Flat ESLint config for the mobile app, built on the shared Expo ruleset.
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");
const globals = require("globals");
const noAccentAsText = require("./eslint-rules/no-accent-as-text");

module.exports = defineConfig([
  expoConfig,
  {
    plugins: {
      fatty: { rules: { "no-accent-as-text": noAccentAsText } },
    },
    rules: {
      "fatty/no-accent-as-text": "error",
    },
  },
  {
    // Plain CommonJS Node scripts (the eslint-rules themselves), not RN/Expo code.
    files: ["eslint-rules/**/*.js"],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ["eslint-rules/**/*.test.js"],
    languageOptions: {
      globals: { ...globals.node, ...globals.jest },
    },
  },
  {
    ignores: ["dist/*", ".expo/*", "node_modules/*", "coverage/*"],
  },
]);
