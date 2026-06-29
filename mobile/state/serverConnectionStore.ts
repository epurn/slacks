/**
 * On-device persistence for the connected Fatty server URL (FTY-107).
 *
 * The server base URL is **non-secret configuration** (see `api/config.ts`): it
 * is the address of the user's own server, not a credential. So it is stored in
 * a normal on-device JSON file via expo-file-system — the same seam appearance
 * uses — and deliberately **not** in `expo-secure-store`, which is reserved for
 * the FTY-090 bearer token. No token, password, or secret is ever written here.
 *
 * A missing, unreadable, or corrupt file is treated as **no connection**
 * (`null`): a first launch routes to the connect screen rather than failing.
 *
 * The seam is injectable so the connect screen / provider tests can drive it
 * without the platform filesystem.
 */

import { File, Paths } from "expo-file-system";

/** Persistence seam for the on-device connected server URL. */
export interface ServerConnectionStore {
  /** Load the connected base URL, or `null` when none is stored / it is unusable. */
  load(): Promise<string | null>;
  /** Persist the connected base URL (already validated + normalized). */
  save(baseUrl: string): Promise<void>;
  /** Forget the connected server (the "change / clear server" affordance). */
  clear(): Promise<void>;
}

interface StoredConnection {
  baseUrl?: unknown;
}

function getConnectionFile(): File {
  return new File(Paths.document, "fatty-server-connection.json");
}

async function readStored(): Promise<StoredConnection> {
  try {
    const file = getConnectionFile();
    if (!file.exists) return {};
    return JSON.parse(await file.text()) as StoredConnection;
  } catch {
    return {};
  }
}

/** File-based on-device connection store backed by expo-file-system. */
export const fileServerConnectionStore: ServerConnectionStore = {
  async load(): Promise<string | null> {
    const data = await readStored();
    return typeof data.baseUrl === "string" && data.baseUrl !== ""
      ? data.baseUrl
      : null;
  },

  async save(baseUrl: string): Promise<void> {
    getConnectionFile().write(JSON.stringify({ baseUrl }));
  },

  async clear(): Promise<void> {
    const file = getConnectionFile();
    if (file.exists) file.delete();
  },
};
