import { mockApi } from "../test/http";
import { admin } from "../test/fixtures";
import { api, ApiError, configureClient, NetworkError, qs } from "./client";

function useToken(token: string | null) {
  const onUnauthorized = vi.fn();
  configureClient({ getToken: () => token, onUnauthorized });
  return onUnauthorized;
}

describe("api client", () => {
  it("sends the bearer token", async () => {
    useToken("abc");
    const { fetchMock } = mockApi({ "GET /auth/me": [200, admin] });
    await expect(api.me()).resolves.toEqual(admin);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });

  it("turns a string detail into one message", async () => {
    useToken(null);
    mockApi({ "POST /auth/login": [403, { detail: "Account awaiting admin approval" }] });
    const failure = await api.login("ben", "secret123").catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 403, messages: ["Account awaiting admin approval"] });
  });

  it("keeps backend validation lines and formats framework validation errors", async () => {
    useToken("abc");
    mockApi({
      "POST /patients/p1/visits": [422, { detail: [
        "bp_systolic: required",
        { loc: ["body", "visit_date"], msg: "Input should be a valid date", type: "date_parsing" },
      ] }],
    });
    const failure = await api.createVisit("p1", {
      visit_date: "x", values: {}, note: null, status: "draft", suggestion_id: null, ai_accepted_fields: [],
    }).catch((error) => error);
    expect(failure.messages).toEqual(["bp_systolic: required", "visit_date: Input should be a valid date"]);
  });

  it("signs out on 401 only when a token was sent", async () => {
    const withToken = useToken("abc");
    mockApi({ "GET /dashboard": [401, { detail: "Not signed in" }] });
    await expect(api.dashboard()).rejects.toBeInstanceOf(ApiError);
    expect(withToken).toHaveBeenCalledOnce();
    const withoutToken = useToken(null);
    mockApi({ "POST /auth/login": [401, { detail: "Wrong username or password" }] });
    await expect(api.login("ana", "nope")).rejects.toBeInstanceOf(ApiError);
    expect(withoutToken).not.toHaveBeenCalled();
  });

  it("reports an unreachable server as a NetworkError", async () => {
    useToken("abc");
    mockApi({ "GET /dashboard": "network" });
    await expect(api.dashboard()).rejects.toBeInstanceOf(NetworkError);
  });

  it("returns undefined for 204 responses", async () => {
    useToken("abc");
    mockApi({ "POST /auth/logout": [204] });
    await expect(api.logout()).resolves.toBeUndefined();
  });

  it("builds query strings without empty values", () => {
    expect(qs({ q: "", limit: 25, state: undefined, offset: 0 })).toBe("?limit=25&offset=0");
    expect(qs({})).toBe("");
  });
});
