'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import './login.css';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();

      if (res.ok) {
        router.push('/ide/');
      } else {
        setError(data.error || 'Login failed');
      }
    } catch {
      setError('An error occurred during login');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="main-container">
      <div className="container-narrow">
        <div className="masthead">
          <h3 className="muted"><a href="/">CLOUDPEBBLE</a></h3>
        </div>
        <div className="row-fluid">
          <div className="span12 well">
            {error && (
              <div className="alert alert-error">{error}</div>
            )}
            <form className="form-horizontal" onSubmit={handleSubmit}>
              <div className="control-group">
                <label className="control-label">USERNAME:</label>
                <div className="controls">
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
              </div>
              <div className="control-group">
                <label className="control-label">PASSWORD:</label>
                <div className="controls">
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
              </div>
              <div className="form-actions">
                <p>
                  <button className="btn btn-primary" type="submit" disabled={loading}>
                    {loading ? 'LOGGING IN...' : 'LOG IN'}
                  </button>
                </p>
                <p>
                  <a href="/accounts/password/reset/">Forgotten password?</a>
                </p>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
