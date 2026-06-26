// Babel configuration for the Expo app. `babel-preset-expo` ships with `expo`
// and powers both Metro bundling and the Jest (`jest-expo`) transform.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
  };
};
