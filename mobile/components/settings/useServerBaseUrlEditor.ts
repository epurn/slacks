/**
 * The Settings server-address editor (FTY-405).
 *
 * Self-hosters need to repoint the app at a different Slacks server without
 * reinstalling — the connect screen (FTY-107) establishes the first connection,
 * this is the same control living in Settings → ACCOUNT & SERVER for every later
 * change. It owns the whole non-visual lifecycle so `AccountSection` stays
 * presentational and `useSettingsController` does not grow another concern.
 *
 * The address the user types is **untrusted** and reuses the connect screen's
 * strict validation (`api/serverConnection`): `http(s)` only, canonicalized, and
 * probed with `GET /healthz` before anything is persisted. A malformed or
 * unreachable address is rejected in place with plain copy — it never silently
 * repoints the app at a dead host.
 *
 * **Session isolation is the security contract here.** A bearer token minted by
 * server A is meaningless — and must never be replayed — against server B, so a
 * confirmed change *signs out first*, then persists the new base URL, then routes
 * to sign-in for the new server. Clearing before connecting means there is never
 * a window in which the new base URL is live while the old server's token is
 * still held. Because the change is destructive to the session, it is explicitly
 * confirmed: the probe success moves the editor into a `confirm` phase whose copy
 * says what will happen, and only that confirmation switches.
 *
 * Nothing here is logged and no token is read — the server URL is non-secret
 * configuration (`api/config.ts`), the token is never touched beyond `signOut()`.
 */

import { useCallback, useState } from 'react';

import { defaultApiBaseUrl } from '@/api/config';
import {
  displayHost,
  probeServer,
  validateServerUrl,
} from '@/api/serverConnection';
import { useConnection } from '@/state/connection';
import { useSessionController } from '@/state/session';

import { useSettingsVisualReviewSubState } from './visualReviewPresets';

/** The editor's transient interaction phase. */
type ServerEditPhase = 'closed' | 'editing' | 'probing' | 'confirm';

export interface ServerBaseUrlEditorProps {
  /**
   * Called after the switch is confirmed, the session is cleared and the new
   * base URL is live — the screen routes to sign-in for the new server.
   */
  onSwitched: () => void;
  /** Injectable reachability probe; defaults to the real `GET /healthz` probe. */
  probeFn?: typeof probeServer;
}

export interface ServerBaseUrlEditor {
  /** The base URL every API call currently targets. */
  readonly currentBaseUrl: string;
  readonly phase: ServerEditPhase;
  /** The address being edited (raw user input while `editing`). */
  readonly draft: string;
  /** The validated address awaiting confirmation, or `null`. */
  readonly pending: string | null;
  /** In-place rejection copy, or `null`. Never contains a secret. */
  readonly error: string | null;
  open(): void;
  cancel(): void;
  setDraft(value: string): void;
  /** Fill the field with the app's default server address. */
  useDefault(): void;
  /** Validate + probe the draft; on success move to the confirm phase. */
  submit(): Promise<void>;
  /** Confirm the destructive switch: sign out, repoint, route to sign-in. */
  confirmSwitch(): Promise<void>;
}

/**
 * Copy for an unreachable host. Names the host so the user can see *which*
 * address failed, and says the two things that are actually actionable —
 * without leaking a status code or a stack.
 */
function unreachableCopy(url: string): string {
  return `Can't reach ${displayHost(url)}. Check the address and that your server is running.`;
}

export function useServerBaseUrlEditor({
  onSwitched,
  probeFn = probeServer,
}: ServerBaseUrlEditorProps): ServerBaseUrlEditor {
  const { connection, connect } = useConnection();
  const { session, signOut } = useSessionController();

  // The live target, in the same priority order `resolveApiBaseUrl()` uses: the
  // persisted connection, else the server the current session is bound to, else
  // the build-time default.
  const currentBaseUrl = connection ?? session?.serverUrl ?? defaultApiBaseUrl();

  // E2E-only visual-review seam (FTY-267 convention): the `settings.server_edit`
  // / `settings.server_switch` presets mount with the editor already open, so a
  // screenshot can reach it without a scripted tap. Always `null` outside E2E
  // mode, so release/dev behaviour is unchanged.
  const visualReviewSubState = useSettingsVisualReviewSubState();
  const openAtMount = visualReviewSubState === 'server_edit';

  const [phase, setPhase] = useState<ServerEditPhase>(
    openAtMount ? 'editing' : 'closed',
  );
  const [draft, setDraftState] = useState<string>(() =>
    openAtMount ? currentBaseUrl : '',
  );
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const open = useCallback(() => {
    setDraftState(currentBaseUrl);
    setPending(null);
    setError(null);
    setPhase('editing');
  }, [currentBaseUrl]);

  const cancel = useCallback(() => {
    setPhase('closed');
    setPending(null);
    setError(null);
  }, []);

  const setDraft = useCallback((value: string) => {
    setDraftState(value);
    // Editing clears the previous rejection so the error never outlives the
    // input that caused it.
    setError(null);
  }, []);

  const useDefault = useCallback(() => {
    setDraftState(defaultApiBaseUrl());
    setError(null);
  }, []);

  const submit = useCallback(async () => {
    if (phase === 'probing') return;
    const result = validateServerUrl(draft);
    if (!result.ok) {
      setError(result.reason);
      setPhase('editing');
      return;
    }
    // Re-saving the address already in use changes nothing, so it must not cost
    // the user their session.
    if (result.url === currentBaseUrl) {
      cancel();
      return;
    }
    setError(null);
    setPhase('probing');
    const outcome = await probeFn(result.url);
    if (outcome !== 'reachable') {
      setError(unreachableCopy(result.url));
      setPhase('editing');
      return;
    }
    setPending(result.url);
    setPhase('confirm');
  }, [cancel, currentBaseUrl, draft, phase, probeFn]);

  const confirmSwitch = useCallback(async () => {
    if (pending === null) return;
    // Order is the security contract: drop the old server's token *before* the
    // new base URL goes live, so no request can ever carry it to the new host.
    await signOut();
    await connect(pending);
    setPhase('closed');
    setPending(null);
    setError(null);
    onSwitched();
  }, [connect, onSwitched, pending, signOut]);

  return {
    currentBaseUrl,
    phase,
    draft,
    pending,
    error,
    open,
    cancel,
    setDraft,
    useDefault,
    submit,
    confirmSwitch,
  };
}
