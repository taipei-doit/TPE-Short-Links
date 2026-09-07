import type { User } from 'firebase/auth';
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const EMAIL_FOR_SIGN_IN_KEY = 'emailForSignIn';

/** 對外網域（url.taipei）純屬公眾服務，完全不載入 Firebase——
 *  登入與管理一律走 admin.url.taipei。 */
const IS_PUBLIC_HOST = window.location.hostname === 'url.taipei';

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  requestLoginLink: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

/**
 * Firebase 一律動態載入：公開頁（聲明、查核、QR）首屏不必下載與解析
 * 驗證 SDK，登入狀態在 SDK 就緒後才補上。對外 API 與原版完全相同。
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    if (IS_PUBLIC_HOST) {
      setLoading(false);
      return;
    }
    let alive = true;
    let unsub: (() => void) | undefined;

    (async () => {
      const [{ auth }, fb] = await Promise.all([import('../firebase'), import('firebase/auth')]);
      if (!alive) return;

      // 魔術連結著陸：先完成登入再掛狀態監聽
      if (fb.isSignInWithEmailLink(auth, window.location.href)) {
        let email = window.localStorage.getItem(EMAIL_FOR_SIGN_IN_KEY);
        if (!email) {
          email = window.prompt('請輸入您申請登入連結時使用的電子郵件') ?? '';
        }
        if (email) {
          try {
            await fb.signInWithEmailLink(auth, email, window.location.href);
            window.localStorage.removeItem(EMAIL_FOR_SIGN_IN_KEY);
            // 清掉網址上的一次性參數，重新整理才不會重跑登入
            window.history.replaceState({}, document.title, window.location.pathname || '/');
          } catch (err) {
            console.error('Sign-in from link failed:', err);
          }
        }
      }

      unsub = auth.onAuthStateChanged((u) => {
        if (!alive) return;
        setUser(u);
        setLoading(false);
      });
    })();

    return () => {
      alive = false;
      unsub?.();
    };
  }, []);

  const requestLoginLink = useCallback(async (email: string) => {
    const [{ default: app }, { getFunctions, httpsCallable }] = await Promise.all([
      import('../firebase'),
      import('firebase/functions'),
    ]);
    const fn = getFunctions(app);
    const sendAdminLoginLink = httpsCallable<{ email: string }>(fn, 'sendAdminLoginLink');
    window.localStorage.setItem(EMAIL_FOR_SIGN_IN_KEY, email);
    await sendAdminLoginLink({ email });
  }, []);

  const signOut = useCallback(async () => {
    const [{ auth }, fb] = await Promise.all([import('../firebase'), import('firebase/auth')]);
    await fb.signOut(auth);
    navigate('/login');
  }, [navigate]);

  const value: AuthContextValue = {
    user,
    loading,
    requestLoginLink,
    signOut,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
