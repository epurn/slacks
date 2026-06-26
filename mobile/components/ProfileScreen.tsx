import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ProfileApiError, putProfile, type ProfileDTO } from "@/api/profile";
import { ProfileForm } from "@/components/ProfileForm";
import { useSession, toProfileSession, type Session } from "@/state/session";
import type { ProfileUpdatePayload } from "@/state/profile";

/** Resolve the device IANA timezone, falling back to UTC. */
function deviceTimezone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz && tz.length > 0 ? tz : "UTC";
  } catch {
    return "UTC";
  }
}

/**
 * Profile capture container (FTY-021). Wires the presentational `ProfileForm`
 * to the FTY-020 profile API for the authenticated user.
 *
 * Until the mobile sign-in flow lands (a separate story), there is no session
 * on the device, so this renders a clear, nonjudgmental "sign in to save"
 * state. The capture form itself — validation, unit conversion, accessibility —
 * is fully covered by tests regardless.
 */
export function ProfileScreen({
  session: sessionOverride,
  save = putProfile,
  now = new Date(),
  timezone = deviceTimezone(),
}: {
  /**
   * Injectable session for tests. When omitted, the live session seam is used;
   * pass `null` to force the signed-out state explicitly.
   */
  session?: Session;
  /** Injectable persistence call; defaults to the real API client. */
  save?: typeof putProfile;
  now?: Date;
  timezone?: string;
} = {}) {
  const liveSession = useSession();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saved, setSaved] = useState<ProfileDTO | null>(null);

  const handleSubmit = useCallback(
    async (payload: ProfileUpdatePayload) => {
      if (!session) {
        return;
      }
      setSubmitting(true);
      setSubmitError(null);
      try {
        const stored = await save(toProfileSession(session), payload);
        setSaved(stored);
      } catch (error) {
        setSubmitError(
          error instanceof ProfileApiError
            ? error.message
            : "We couldn't save your profile. Please try again.",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [session, save],
  );

  if (!session) {
    return <SignInRequired />;
  }

  if (saved) {
    return <Saved />;
  }

  return (
    <ProfileForm
      currentYear={now.getFullYear()}
      timezone={timezone}
      onSubmit={handleSubmit}
      submitting={submitting}
      submitError={submitError}
    />
  );
}

function SignInRequired() {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.center, { paddingTop: insets.top + 24 }]}>
      <Text style={styles.title} accessibilityRole="header">
        Sign in to save your profile
      </Text>
      <Text style={styles.body}>
        Your profile is stored privately against your account. Sign in to enter
        and save it.
      </Text>
    </View>
  );
}

function Saved() {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.center, { paddingTop: insets.top + 24 }]}>
      <Text style={styles.title} accessibilityRole="header">
        Profile saved
      </Text>
      <Text style={styles.body}>
        Your details are saved. We&apos;ll use them to estimate your daily
        targets.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    backgroundColor: "#F2F2F7",
    paddingHorizontal: 24,
    alignItems: "center",
  },
  title: {
    fontSize: 24,
    fontWeight: "700",
    color: "#1C1C1E",
    textAlign: "center",
  },
  body: {
    fontSize: 15,
    color: "#8E8E93",
    textAlign: "center",
    marginTop: 12,
  },
});
