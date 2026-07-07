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
    expect(script).toContain('METRO_PORT="${E2E_METRO_PORT:-8081}"');
    expect(script).toContain('trap cleanup_metro EXIT');
    expect(script).toContain(
      'npx expo run:android $BUILD_CACHE_FLAG --variant debug --no-bundler',
    );
    expect(script).not.toContain('npx expo run:android $BUILD_CACHE_FLAG --configuration');
    // No --simulator flag: Expo 57's run:ios rejects it, and the simulator is
    // already the default target when --device is not passed. No -p/--port
    // either: Expo 57 rejects combining a port with --no-bundler, and Metro's
    // port is carried by expo start + RCT_jsLocation.
    expect(script).toContain('ios_run_args=(--configuration Debug --no-bundler)');
    expect(script).not.toContain('ios_run_args=(--configuration Debug --no-bundler -p');
    expect(script).not.toContain('ios_run_args=(--configuration Debug --no-bundler --port');
    expect(script).toContain('npx expo run:ios $BUILD_CACHE_FLAG "${ios_run_args[@]}"');
    expect(script).not.toContain('run:ios $BUILD_CACHE_FLAG --configuration Debug --simulator');
    expect(script).toContain('E2E_MAESTRO_TIMEOUT_SECONDS:-720');
    expect(script).toContain('maestro_args=(test)');
    expect(script).toContain('MAESTRO_CLI_NO_ANALYTICS=1 maestro "${maestro_args[@]}"');
  });

  it('threads E2E_UDID / E2E_METRO_PORT to every device- and port-touching command', () => {
    const script = readText(scriptPath);

    // Header documents both vars.
    expect(script).toMatch(/#\s+E2E_UDID\s/);
    expect(script).toMatch(/#\s+E2E_METRO_PORT\s/);

    // Every device-/port-touching call site derives from the two vars.
    expect(script).toContain('ios_run_args+=(-d "$E2E_UDID")');
    expect(script).toContain('maestro_args+=(--udid "$E2E_UDID")');
    expect(script).toContain(
      'xcrun simctl spawn "$E2E_UDID" defaults write com.fatty RCT_jsLocation "localhost:$METRO_PORT"',
    );

    // The corrected re-point mechanism (RCT_jsLocation), not the no-op dev-client deep link.
    expect(script).not.toContain('expo-development-client');
    expect(script).not.toContain('simctl openurl');

    // No port-touching command hardcodes 8081 — everything derives from
    // $METRO_PORT, whose only default lives in the single assignment below.
    expect(script).toContain('METRO_PORT="${E2E_METRO_PORT:-8081}"');
    expect(script).not.toMatch(/--port\s+"?8081"?/);
    expect(script).not.toMatch(/-p\s+"?8081"?/);
    expect(script).not.toMatch(/:8081/);

    // No device-touching command falls back to the "booted" specifier.
    const deviceCommandLines = script
      .split('\n')
      .filter((line) => /simctl|maestro test|expo run:(ios|android)/.test(line));
    for (const line of deviceCommandLines) {
      expect(line).not.toMatch(/\bbooted\b/);
    }
  });

  it('genuinely ignores E2E_UDID / E2E_METRO_PORT on Android', () => {
    const script = readText(scriptPath);

    // Android must not honour the iOS-only vars. They are unset BEFORE
    // METRO_PORT/E2E_UDID resolve, so Metro stays on its 8081 default and no
    // device targeting leaks into the Android build — matching today's path.
    expect(script).toMatch(
      /\[ "\$PLATFORM" = "android" \][\s\S]*?unset E2E_UDID E2E_METRO_PORT[\s\S]*?METRO_PORT="\$\{E2E_METRO_PORT:-8081\}"/,
    );
  });

  it('runs directory-level Maestro flows against literal app IDs', () => {
    const script = readText(scriptPath);
    const expectedAppId = appConfig.expo.android?.package;

    expect(expectedAppId).toBe('com.fatty');
    expect(script).toContain('maestro_args=(test)');
    expect(script).toContain('maestro_args+=(.maestro/)');
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
