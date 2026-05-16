import { useState } from 'react';
import { setTokens } from '../api';
import type { TokenResponse } from '../types';

interface Props {
  onAuth: (email: string) => void;
}

export default function AuthScreen({ onAuth }: Props) {
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/api/v1/auth/login' : '/api/v1/auth/signup';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json() as TokenResponse & { detail?: string };
      if (!res.ok) {
        setError(data.detail ?? 'Authentication failed');
        return;
      }
      setTokens(data.access_token, data.refresh_token);
      onAuth(email);
    } catch {
      setError('Network error — is the server running?');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-overlay">
      <div className="auth-card">
        <div className="auth-logo">
          <svg className="auth-gem" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z" stroke="currentColor" strokeWidth="1.5" fill="none"/>
            <path d="M12 2L12 22M2 8L22 8M2 16L22 16" stroke="currentColor" strokeWidth="0.75" opacity="0.4"/>
          </svg>
          <span className="auth-logo-text">DocChat <em>Agent</em></span>
        </div>

        <div className="auth-tabs">
          <button
            className={`auth-tab ${mode === 'login' ? 'active' : ''}`}
            onClick={() => { setMode('login'); setError(''); }}
          >Sign in</button>
          <button
            className={`auth-tab ${mode === 'signup' ? 'active' : ''}`}
            onClick={() => { setMode('signup'); setError(''); }}
          >Create account</button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            className="auth-input"
            type="email"
            placeholder="Email"
            autoComplete="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
          />
          <input
            className="auth-input"
            type="password"
            placeholder="Password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />
          <p className="auth-error">{error}</p>
          <button className="auth-submit" type="submit" disabled={loading}>
            {loading ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  );
}
