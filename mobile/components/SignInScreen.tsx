/**
 * Sign-in / create-account screen (FTY-091) — the auth half of the
 * self-host-first first run (UX design §4d).
 *
 * A single screen that toggles between **Sign in** and **Create account**; both
 * modes collect an email + password and authenticate **against the server the
 * user connected to in FTY-107**. The connected base URL is read from the
 * connection seam and shown ("Signing in to {host}") so the user can confirm it
 * is their own server before typing credentials — an anti-phishing signal,
 * because the target can originate from a scanned QR (FTY-107). The actual auth
 * call and the token store live in FTY-090; this screen is presentation,
 * validation, and routing.
 *
 * Security / privacy:
 * - The password field is `secureTextEntry`; the password is never logged and
 *   never echoed into an error (errors carry only status-derived copy).
 * - The bad-credentials surface is **non-enumerating**: an unknown email and a
 *   wrong password show the identical `401` message, preserving the backend's
 *   no-account-existence-oracle property.
 *
 * Built from FTY-097 primitives (themed Text / Button / Card, amber accent,
 * system-material surfaces) so it renders correctly in light and dark; iOS-first
 * and accessible (VoiceOver labels, ≥44pt targets, secure text entry).
 */

import { useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AuthApiError } from "@/api/auth";
import { displayHost } from "@/api/serverConnection";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui";
import { ThemedText } from "@/components/ui/ThemedText";
import { useConnection } from "@/state/connection";
import { useSessionController } from "@/state/session";
import { radius, spacing, typeScale, useTheme } from "@/theme";

/** Which form the single screen is showing. */
export type AuthMode = "signin" | "create";

/** Password length bounds, mirroring the identity-and-profile contract. */
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;

/**
 * A deliberately permissive email shape check: a single `@` with non-empty,
 * dot-free local part and a dotted domain. The backend is the source of truth
 * (it rejects bad addresses with `422`); this only catches obvious typos before
 * a network round-trip, so it must never be stricter than the server.
 */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Validate the email shape; returns an inline message or `null` when valid. */
export function emailError(email: string): string | null {
  return EMAIL_RE.test(email.trim())
    ? null
    : "Enter a valid email address.";
}

/** Validate the password length; returns an inline message or `null`. */
export function passwordError(password: string): string | null {
  if (password.length < PASSWORD_MIN || password.length > PASSWORD_MAX) {
    return `Use a password of ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.`;
  }
  return null;
}

export interface SignInScreenProps {
  /**
   * Called after a successful sign-in / create-account (the session is already
   * persisted by FTY-090). The route decides where to go next — onboarding when
   * the goal/profile is unset (FTY-103), otherwise Today.
   */
  onAuthenticated: () => void;
  /** Initial mode; defaults to signing in. Injectable for tests. */
  initialMode?: AuthMode;
}

export function SignInScreen({
  onAuthenticated,
  initialMode = "signin",
}: SignInScreenProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { connection } = useConnection();
  const { signIn, createAccount } = useSessionController();

  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailMsg, setEmailMsg] = useState<string | null>(null);
  const [passwordMsg, setPasswordMsg] = useState<string | null>(null);
  // Form-level failure (auth rejection / unreachable). Never carries the
  // password or any account-existence signal.
  const [formError, setFormError] = useState<string | null>(null);
  // A 409 on create-account: offer "sign in instead" rather than a dead-end.
  const [existsConflict, setExistsConflict] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const isSignIn = mode === "signin";
  const host = connection !== null ? displayHost(connection) : null;

  const clearErrors = () => {
    setEmailMsg(null);
    setPasswordMsg(null);
    setFormError(null);
    setExistsConflict(false);
  };

  const switchMode = (next: AuthMode) => {
    if (next === mode) return;
    setMode(next);
    clearErrors();
  };

  const handleSubmit = async () => {
    if (submitting) return;
    clearErrors();

    // Client-side validation before any network call.
    const eMsg = emailError(email);
    const pMsg = passwordError(password);
    if (eMsg !== null || pMsg !== null) {
      setEmailMsg(eMsg);
      setPasswordMsg(pMsg);
      return;
    }

    // The connect gate guarantees a connection before this screen renders; guard
    // defensively rather than posting credentials to an unknown target.
    if (connection === null) {
      setFormError("Connect to your server first.");
      return;
    }

    setSubmitting(true);
    try {
      if (isSignIn) {
        await signIn(connection, email.trim(), password);
      } else {
        await createAccount(connection, email.trim(), password);
      }
      onAuthenticated();
    } catch (err) {
      if (err instanceof AuthApiError) {
        if (err.status === 409) {
          // Account already exists — surface a switch-to-sign-in affordance.
          setExistsConflict(true);
        } else if (err.status === 422) {
          // Generic "check your details" (the client already pre-validates).
          setFormError("Check your details and try again.");
        } else {
          // 401 (non-enumerating), 429, and other statuses carry their own
          // status-derived, password-free message from the auth client.
          setFormError(err.message);
        }
      } else {
        // A network-layer failure (fetch rejected) — retryable, never a dead-end.
        setFormError(
          `Couldn't reach ${host ?? "your server"}. Check your connection and try again.`,
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  const submitLabel = submitting
    ? isSignIn
      ? "Signing in…"
      : "Creating account…"
    : isSignIn
      ? "Sign in"
      : "Create account";

  const emailBorder = emailMsg !== null ? colors.coral : colors.separator;
  const passwordBorder = passwordMsg !== null ? colors.coral : colors.separator;

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
          {isSignIn ? "Welcome back" : "Create your account"}
        </ThemedText>

        {host !== null ? (
          <ThemedText
            variant="textSecondary"
            style={styles.subtitle}
            accessibilityLabel={`${isSignIn ? "Signing in" : "Creating an account"} on ${host}`}
          >
            {`${isSignIn ? "Signing in to" : "Creating an account on"} ${host}`}
          </ThemedText>
        ) : null}

        {/* Mode toggle — switch between signing in and creating an account. */}
        <SegmentedControl<AuthMode>
          testID="auth-mode-segmented-control"
          accessibilityLabel="Sign in or create an account"
          options={[
            { value: "signin", label: "Sign in" },
            { value: "create", label: "Create account" },
          ]}
          selected={mode}
          onSelect={switchMode}
          style={styles.toggle}
        />

        <Card style={styles.card}>
          <TextInput
            accessibilityLabel="Email"
            value={email}
            onChangeText={(t) => {
              setEmail(t);
              if (emailMsg !== null) setEmailMsg(null);
              if (formError !== null) setFormError(null);
              if (existsConflict) setExistsConflict(false);
            }}
            placeholder="you@example.com"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="email"
            keyboardType="email-address"
            textContentType="emailAddress"
            inputMode="email"
            returnKeyType="next"
            editable={!submitting}
            style={[
              styles.input,
              {
                borderColor: emailBorder,
                backgroundColor: colors.controlBackground,
                color: colors.text,
                fontSize: typeScale.body,
              },
            ]}
          />
          {emailMsg !== null ? (
            <FieldError message={emailMsg} colors={colors} />
          ) : null}

          <TextInput
            accessibilityLabel="Password"
            value={password}
            onChangeText={(t) => {
              setPassword(t);
              if (passwordMsg !== null) setPasswordMsg(null);
              if (formError !== null) setFormError(null);
              if (existsConflict) setExistsConflict(false);
            }}
            placeholder="Password"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete={isSignIn ? "current-password" : "new-password"}
            textContentType={isSignIn ? "password" : "newPassword"}
            returnKeyType="go"
            onSubmitEditing={() => void handleSubmit()}
            editable={!submitting}
            style={[
              styles.input,
              styles.inputSpaced,
              {
                borderColor: passwordBorder,
                backgroundColor: colors.controlBackground,
                color: colors.text,
                fontSize: typeScale.body,
              },
            ]}
          />
          {passwordMsg !== null ? (
            <FieldError message={passwordMsg} colors={colors} />
          ) : null}
        </Card>

        {formError !== null ? (
          <ThemedText
            variant="coral"
            scale="subhead"
            accessibilityLiveRegion="polite"
            accessibilityRole="alert"
            style={styles.error}
          >
            {formError}
          </ThemedText>
        ) : null}

        {existsConflict ? (
          <View
            style={styles.conflict}
            accessibilityLiveRegion="polite"
            accessibilityRole="alert"
          >
            <ThemedText variant="textSecondary" scale="subhead">
              An account already exists for this email.
            </ThemedText>
            <Button
              label="Sign in instead"
              variant="secondary"
              onPress={() => switchMode("signin")}
              style={styles.conflictAction}
            />
          </View>
        ) : null}

        <Button
          label={submitLabel}
          onPress={() => void handleSubmit()}
          disabled={submitting}
          style={styles.action}
        />
      </View>
    </View>
  );
}

/** A calm, in-place inline error for a single field. */
function FieldError({
  message,
  colors,
}: {
  message: string;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <ThemedText
      variant="coral"
      scale="footnote"
      accessibilityRole="alert"
      style={styles.fieldError}
    >
      {message}
    </ThemedText>
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
  toggle: {
    marginBottom: spacing.md,
  },
  card: {
    padding: spacing.base,
  },
  input: {
    minHeight: 44,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
  },
  inputSpaced: {
    marginTop: spacing.md,
  },
  fieldError: {
    marginTop: spacing.xs,
  },
  error: {
    marginTop: spacing.md,
  },
  conflict: {
    marginTop: spacing.md,
    gap: spacing.sm,
  },
  conflictAction: {
    alignSelf: "flex-start",
  },
  action: {
    marginTop: spacing.lg,
  },
});
