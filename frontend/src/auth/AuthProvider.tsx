import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, configureClient, NetworkError } from "../api/client";
import type { User } from "../api/types";
import { Loading, ServerDown } from "../components/Status";
import { clearToken, getToken, setToken } from "./token";

type Auth = {
  user: User | null;
  signIn: (login: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
  setUser: (user: User) => void;
};

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Configure the client during the first render: children's effects run before this component's.
  useState(() =>
    configureClient({
      getToken,
      onUnauthorized: () => {
        clearToken();
        setUser(null);
      },
    }),
  );

  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    let live = true;
    setOffline(false);
    api.me().then(
      (me) => {
        if (!live) return;
        setUser(me);
        setReady(true);
      },
      (error: unknown) => {
        if (!live) return;
        if (error instanceof NetworkError) {
          setOffline(true);
        } else {
          clearToken();
          setReady(true);
        }
      },
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  const signIn = useCallback(async (login: string, password: string) => {
    const result = await api.login(login, password);
    setToken(result.token);
    setUser(result.user);
    return result.user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Forgetting the token below is what signs this browser out.
    }
    clearToken();
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, signIn, signOut, setUser }), [user, signIn, signOut]);
  if (offline) return <ServerDown onRetry={() => setAttempt((n) => n + 1)} />;
  if (!ready) return <Loading />;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
