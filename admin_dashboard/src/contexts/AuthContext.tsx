import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { LoginRequest, TokenResponse, User } from '../types';
import { apiClient } from '../api/client';

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextValue extends AuthState {
  login: (credentials: LoginRequest) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const TOKEN_KEY = 'admin_access_token';
const REFRESH_KEY = 'admin_refresh_token';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    token: localStorage.getItem(TOKEN_KEY),
    isAuthenticated: false,
    isLoading: true,
  });

  const fetchCurrentUser = useCallback(async (token: string) => {
    try {
      const response = await apiClient.get<User>('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      });
      const user = response.data;
      if (user.role !== 'admin') {
        throw new Error('Insufficient permissions');
      }
      setState({ user, token, isAuthenticated: true, isLoading: false });
    } catch {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_KEY);
      setState({ user: null, token: null, isAuthenticated: false, isLoading: false });
    }
  }, []);

  useEffect(() => {
    if (state.token) {
      fetchCurrentUser(state.token);
    } else {
      setState((prev) => ({ ...prev, isLoading: false }));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const login = async (credentials: LoginRequest) => {
    const response = await apiClient.post<TokenResponse>('/api/v1/auth/login', credentials);
    const { access_token, refresh_token } = response.data;
    localStorage.setItem(TOKEN_KEY, access_token);
    localStorage.setItem(REFRESH_KEY, refresh_token);
    setState((prev) => ({ ...prev, token: access_token }));
    await fetchCurrentUser(access_token);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    setState({ user: null, token: null, isAuthenticated: false, isLoading: false });
  };

  return (
    <AuthContext.Provider value={{ ...state, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
