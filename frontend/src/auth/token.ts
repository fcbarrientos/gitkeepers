const KEY = "gk.token";
let memory: string | null = null; // used when the browser blocks storage

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export function setToken(token: string): void {
  memory = token;
  try {
    localStorage.setItem(KEY, token);
  } catch {
    // Memory only: the user signs in again after a reload.
  }
}

export function clearToken(): void {
  memory = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing stored.
  }
}
