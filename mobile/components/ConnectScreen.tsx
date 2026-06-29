/**
 * Connect-to-your-server screen (FTY-107) — the self-host-first first step.
 *
 * The first thing a new user sees: point the app at their own Fatty server by
 * **typing or scanning** its address. The connected server is the network target
 * every later request (including the FTY-091 credentials) is sent to, so both
 * inputs are treated as **untrusted** and pass strict `http(s)`-only validation
 * (`api/serverConnection`) *before* any network call. A reachability probe
 * (`GET /healthz`) confirms the host is a live Fatty server; only then is the
 * normalized base URL persisted and the flow advanced to sign-in (FTY-091).
 *
 * - The setup QR carries the **server URL only** — scanning just fills the field;
 *   no secret is consumed, and the user still creates the account manually later.
 * - An unreachable / timed-out / non-Fatty server shows "Can't reach {host}" with
 *   a Retry, keeps the URL editable, and is never a dead-end.
 *
 * Built from FTY-097 primitives (themed Text / Button / Card, amber accent),
 * correct in light and dark, accessible (VoiceOver labels, ≥44pt targets,
 * Dynamic Type), and calm (no surprise navigation; errors resolve in place).
 */

import { useState } from "react";
import { Modal, StyleSheet, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ThemedText } from "@/components/ui/ThemedText";
import {
  QrScannerScreen,
  type QrScannerScreenProps,
} from "@/components/QrScannerScreen";
import {
  displayHost,
  probeServer,
  validateServerUrl,
} from "@/api/serverConnection";
import { useConnection } from "@/state/connection";
import { spacing, radius, typeScale, useTheme } from "@/theme";

/** The screen's transient interaction phase. */
type Phase = "idle" | "probing" | "invalid" | "unreachable";

export interface ConnectScreenProps {
  /**
   * Called after the address is validated, reachable, and persisted — the route
   * hands off to sign-in (FTY-091). Receives the normalized base URL.
   */
  onConnected: (baseUrl: string) => void;
  /** Injectable probe transport; defaults to the global `fetch`. */
  fetchImpl?: typeof fetch;
  /** Probe timeout in ms; forwarded to `probeServer`. */
  probeTimeoutMs?: number;
  /** Forwarded to the QR scanner's camera permission gate (injectable in tests). */
  permissionsHook?: QrScannerScreenProps["permissionsHook"];
}

export function ConnectScreen({
  onConnected,
  fetchImpl,
  probeTimeoutMs,
  permissionsHook,
}: ConnectScreenProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { connection, connect, clear } = useConnection();

  // Prefill with the currently-connected server when the screen is reached to
  // change it later; first run has no connection and starts empty.
  const [url, setUrl] = useState<string>(connection ?? "");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string>("");
  const [scannerOpen, setScannerOpen] = useState<boolean>(false);

  const probing = phase === "probing";

  const resetError = () => {
    if (phase !== "idle") {
      setPhase("idle");
      setError("");
    }
  };

  const handleChangeText = (text: string) => {
    setUrl(text);
    resetError();
  };

  const handleConnect = async () => {
    if (probing) return;
    const result = validateServerUrl(url);
    if (!result.ok) {
      setPhase("invalid");
      setError(result.reason);
      return;
    }
    setPhase("probing");
    setError("");
    const outcome = await probeServer(result.url, {
      ...(fetchImpl ? { fetchImpl } : {}),
      ...(probeTimeoutMs !== undefined ? { timeoutMs: probeTimeoutMs } : {}),
    });
    if (outcome === "reachable") {
      await connect(result.url);
      onConnected(result.url);
      return;
    }
    setPhase("unreachable");
    setError(`Can't reach ${displayHost(result.url)}`);
  };

  // The scanned QR payload is untrusted: it runs the same validation as a typed
  // address. A valid URL just fills the field (the user still taps Connect); a
  // bad QR is rejected with a gentle message — never auto-accepted or persisted.
  const handleScanned = (value: string) => {
    setScannerOpen(false);
    const result = validateServerUrl(value);
    if (!result.ok) {
      setPhase("invalid");
      setError("That QR isn't a Fatty server URL.");
      return;
    }
    setUrl(result.url);
    setPhase("idle");
    setError("");
  };

  const handleForget = async () => {
    await clear();
    setUrl("");
    setPhase("idle");
    setError("");
  };

  const primaryLabel = probing
    ? "Connecting…"
    : phase === "unreachable"
      ? "Retry"
      : "Connect";

  const inputBorderColor =
    phase === "invalid" || phase === "unreachable"
      ? colors.coral
      : colors.separator;

  return (
    <View
      style={[
        styles.screen,
        {
          backgroundColor: colors.surface,
          paddingTop: insets.top + spacing.xxl,
          paddingBottom: insets.bottom + spacing.lg,
        },
      ]}
    >
      <View style={styles.content}>
        <ThemedText scale="largeTitle" bold style={styles.title}>
          Connect to your Fatty server
        </ThemedText>
        <ThemedText variant="textSecondary" style={styles.subtitle}>
          {"Enter your server's address, or scan its setup QR. Your account lives on your own server."}
        </ThemedText>

        <Card style={styles.card}>
          <TextInput
            accessibilityLabel="Server address"
            value={url}
            onChangeText={handleChangeText}
            onSubmitEditing={() => void handleConnect()}
            placeholder="https://fatty.example.com"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="off"
            inputMode="url"
            keyboardType="url"
            returnKeyType="go"
            editable={!probing}
            style={[
              styles.input,
              {
                borderColor: inputBorderColor,
                backgroundColor: colors.controlBackground,
                color: colors.text,
                fontSize: typeScale.body,
              },
            ]}
          />
        </Card>

        {error !== "" ? (
          <ThemedText
            variant="coral"
            scale="subhead"
            accessibilityLiveRegion="polite"
            accessibilityRole="alert"
            style={styles.error}
          >
            {error}
          </ThemedText>
        ) : null}

        <Button
          label={primaryLabel}
          onPress={() => void handleConnect()}
          disabled={probing}
          style={styles.action}
        />
        <Button
          label="Scan QR"
          variant="secondary"
          onPress={() => setScannerOpen(true)}
          disabled={probing}
          style={styles.action}
        />

        {connection !== null ? (
          <Button
            label="Forget this server"
            variant="secondary"
            onPress={() => void handleForget()}
            disabled={probing}
            style={styles.action}
          />
        ) : null}
      </View>

      <Modal
        visible={scannerOpen}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setScannerOpen(false)}
      >
        <QrScannerScreen
          onScanned={handleScanned}
          onClose={() => setScannerOpen(false)}
          permissionsHook={permissionsHook}
        />
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    paddingHorizontal: spacing.lg,
  },
  content: {
    flex: 1,
    justifyContent: "center",
  },
  title: {
    marginBottom: spacing.sm,
  },
  subtitle: {
    marginBottom: spacing.xl,
    lineHeight: 22,
  },
  card: {
    padding: spacing.xs,
    marginBottom: spacing.md,
  },
  input: {
    minHeight: 44,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
  },
  error: {
    marginBottom: spacing.md,
  },
  action: {
    marginTop: spacing.sm,
  },
});
