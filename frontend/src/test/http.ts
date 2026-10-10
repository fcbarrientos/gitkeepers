import { vi } from "vitest";
import type { User } from "../api/types";

export type Reply = [number, unknown?];
// Request bodies are arbitrary JSON in tests, hence `any`.
export type Route = Reply | "network" | ((body: any, url: URL) => Reply);
export type Call = { method: string; path: string; body: any };

/** Stub fetch with a tiny fake backend keyed "METHOD /path?query", or "METHOD /path" for any query. */
export function mockApi(routes: Record<string, Route>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = init.method ?? "GET";
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path: path + url.search, body });
    const route = routes[`${method} ${path}${url.search}`] ?? routes[`${method} ${path}`];
    if (route === "network") throw new TypeError("Failed to fetch");
    const [status, payload]: Reply =
      route === undefined ? [404, { detail: "Not Found" }] : typeof route === "function" ? route(body, url) : route;
    if (status === 204) return new Response(null, { status });
    return new Response(JSON.stringify(payload ?? null), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export const signedInAs = (user: User): Record<string, Route> => ({ "GET /auth/me": [200, user] });

export const callsTo = (calls: Call[], method: string, path: string) =>
  calls.filter((call) => call.method === method && call.path.split("?")[0] === path);
