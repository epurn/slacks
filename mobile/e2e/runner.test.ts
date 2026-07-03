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
  const maestroDir = path.join(process.cwd(), '.maestro');

  function readText(filePath: string): string {
    return fs.readFileSync(filePath, 'utf8') as string;
  }

  function maestroFlowPaths(): string[] {
    return (fs.readdirSync(maestroDir) as string[])
      .filter((file) => file.endsWith('.yaml'))
      .map((file) => path.join(maestroDir, file));
  }

  it('keeps the generated native app IDs aligned with the Maestro default', () => {
    expect(appConfig.expo.android?.package).toBe('com.fatty');
    expect(appConfig.expo.ios?.bundleIdentifier).toBe('com.fatty');
  });

  it('starts Metro explicitly and builds without Expo owning the bundler', () => {
    const script = readText(scriptPath);

    expect(script).toContain(
      'npx expo start --dev-client --host localhost --port "$METRO_PORT"',
    );
    expect(script).toContain('METRO_PORT="8081"');
    expect(script).toContain('trap cleanup_metro EXIT');
    expect(script).toContain(
      'npx expo run:android $BUILD_CACHE_FLAG --variant debug --no-bundler',
    );
    expect(script).not.toContain('npx expo run:android $BUILD_CACHE_FLAG --configuration');
    // No --simulator flag: Expo 57's run:ios rejects it, and the simulator is
    // already the default target when --device is not passed.
    expect(script).toContain(
      'npx expo run:ios $BUILD_CACHE_FLAG --configuration Debug --no-bundler',
    );
    expect(script).not.toContain('run:ios $BUILD_CACHE_FLAG --configuration Debug --simulator');
    expect(script).toContain('E2E_MAESTRO_TIMEOUT_SECONDS:-420');
    expect(script).toContain('MAESTRO_CLI_NO_ANALYTICS=1 maestro test .maestro/');
  });

  it('runs directory-level Maestro flows against literal app IDs', () => {
    const script = readText(scriptPath);
    const expectedAppId = appConfig.expo.android?.package;

    expect(expectedAppId).toBe('com.fatty');
    expect(script).toContain('maestro test .maestro/');
    expect(script).not.toContain('APP_BUNDLE_ID');

    for (const flowPath of maestroFlowPaths()) {
      const flow = readText(flowPath);

      expect(flow).toContain(`appId: ${expectedAppId}`);
      expect(flow).not.toMatch(/^appId:\s*\$/m);
      expect(flow).toContain('- launchApp:');
      expect(flow).not.toContain('testId:');
      expect(flow).not.toContain('label:');
    }
  });
});
