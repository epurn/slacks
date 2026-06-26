// Flat ESLint config for the mobile app, built on the shared Expo ruleset.
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ["dist/*", ".expo/*", "node_modules/*", "coverage/*"],
  },
]);
