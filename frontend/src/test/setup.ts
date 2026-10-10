import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
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

// The app shell renders several live status widgets; under parallel test load the first paint can pass 1 s.
configure({ asyncUtilTimeout: 5000 });

// jsdom has no object URLs; downloads only need a placeholder.
URL.createObjectURL = vi.fn(() => "blob:test");
URL.revokeObjectURL = vi.fn();

afterEach(() => {
  cleanup();
  clearToken();
  localStorage.clear();
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
