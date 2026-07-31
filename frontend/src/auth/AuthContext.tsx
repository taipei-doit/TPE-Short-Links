import {
  isSignInWithEmailLink,
  signInWithEmailLink,
  signOut as firebaseSignOut,
  type User,
} from 'firebase/auth';
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { auth } from '../firebase';

const EMAIL_FOR_SIGN_IN_KEY = 'emailForSignIn';

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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  // Complete sign-in when user lands on the app via the magic link
  useEffect(() => {
    if (!auth || !window.location.href) {
      setLoading(false);
      return;
    }
    const handleEmailLink = async () => {
      if (!isSignInWithEmailLink(auth, window.location.href)) {
        setLoading(false);
        return;
      }
      let email = window.localStorage.getItem(EMAIL_FOR_SIGN_IN_KEY);
      if (!email) {
        email = window.prompt('Please confirm your email address') ?? '';
        if (!email) {
          setLoading(false);
          return;
        }
      }
      try {
        await signInWithEmailLink(auth, email, window.location.href);
        window.localStorage.removeItem(EMAIL_FOR_SIGN_IN_KEY);
        // Remove the link params from URL so refreshing doesn't re-trigger
        window.history.replaceState({}, document.title, window.location.pathname || '/');
      } catch (err) {
        console.error('Sign-in from link failed:', err);
      } finally {
        setLoading(false);
      }
    };
    handleEmailLink();
  }, []);

  // Auth state listener (after initial link handling)
  useEffect(() => {
    const unsub = auth.onAuthStateChanged((u) => {
      setUser(u);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  const requestLoginLink = useCallback(async (email: string) => {
    const { getFunctions, httpsCallable } = await import('firebase/functions');
    const fn = getFunctions(auth.app);
    const sendAdminLoginLink = httpsCallable<{ email: string }>(fn, 'sendAdminLoginLink');
    window.localStorage.setItem(EMAIL_FOR_SIGN_IN_KEY, email);
    await sendAdminLoginLink({ email });
  }, []);

  const signOut = useCallback(async () => {
    await firebaseSignOut(auth);
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
