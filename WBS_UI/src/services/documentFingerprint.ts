/** Exact-byte identity only. Hashes never authorize access to another workspace. */
export async function documentFingerprint(file: File, maximumBytes: number): Promise<string | null> {
  if (file.size === 0 || file.size > maximumBytes) {
    throw new Error('The document is empty or exceeds the upload size limit.');
  }
  // Upload still receives independent server-side validation when Web Crypto is unavailable.
  if (!globalThis.crypto?.subtle) return null;
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}


/** Request identity does not require the secure-context-only randomUUID API. */
export function createWorkflowRequestKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
