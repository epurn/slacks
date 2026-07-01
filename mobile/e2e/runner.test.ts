/**
 * Static checks for the Maestro E2E runner contract.
 *
 * The full flow still runs in CI on an emulator. These tests catch cheap
 * regressions in the shell/config glue before the emulator job gets that far.
 */

type AppConfig = {
  expo: {
    android?: { package?: string };
    ios?: { bundleIdentifier?: string };
  };
};

describe('verify-e2e runner contract', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('fs');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const path = require('path');
  const appConfig = require('../app.json') as AppConfig;
  const scriptPath = path.join(process.cwd(), 'verify-e2e.sh');

  it('keeps the generated native app IDs aligned with the Maestro default', () => {
    expect(appConfig.expo.android?.package).toBe('com.fatty');
    expect(appConfig.expo.ios?.bundleIdentifier).toBe('com.fatty');
  });

  it('uses platform-specific Expo build flags', () => {
    const script = fs.readFileSync(scriptPath, 'utf8') as string;

    expect(script).toContain('npx expo run:android $BUILD_CACHE_FLAG --variant debug');
    expect(script).not.toContain('npx expo run:android $BUILD_CACHE_FLAG --configuration');
    expect(script).toContain(
      'npx expo run:ios $BUILD_CACHE_FLAG --configuration Debug --simulator',
    );
  });
});
