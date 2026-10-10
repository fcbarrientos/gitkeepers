import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { clearToken } from "../auth/token";

// React Router builds Requests with jsdom's AbortSignal, which Node's Request rejects.
// Tests never abort navigations, so drop the signal.
class TestRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(input, init && { ...init, signal: undefined });
  }
}
globalThis.Request = TestRequest;

afterEach(() => {
  cleanup();
  clearToken();
  localStorage.clear();
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
