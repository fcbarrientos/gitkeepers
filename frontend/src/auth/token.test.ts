import { clearToken, getToken, setToken } from "./token";

describe("token storage", () => {
  it("stores, reads and clears the token", () => {
    setToken("t1");
    expect(getToken()).toBe("t1");
    expect(localStorage.getItem("gk.token")).toBe("t1");
    clearToken();
    expect(getToken()).toBeNull();
  });

  it("falls back to memory when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    setToken("t2");
    expect(getToken()).toBe("t2");
  });
});
