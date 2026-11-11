// Client side auth state. The JWT lives in localStorage (simplest approach that works with the
// Next rewrite proxy and EventSource). Every access is wrapped because storage can be blocked.

const TOKEN_KEY = "gigbid.token";
const USER_KEY = "gigbid.user";

export type StoredUser = { id: string; email: string; persona: string };

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getUser(): StoredUser | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as StoredUser) : null;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: StoredUser): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* storage blocked, session lasts only until reload */
  }
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

function onboardKey(userId: string): string {
  return `gigbid.onboarded.${userId}`;
}

export function isOnboarded(userId: string): boolean {
  try {
    return window.localStorage.getItem(onboardKey(userId)) === "1";
  } catch {
    return false;
  }
}

export function markOnboarded(userId: string): void {
  try {
    window.localStorage.setItem(onboardKey(userId), "1");
  } catch {
    /* ignore */
  }
}
