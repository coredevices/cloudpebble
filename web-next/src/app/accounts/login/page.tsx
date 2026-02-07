'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';

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
      {/* Custom container - from Django inline style */}
      <style>{`
        .container-narrow {
          margin: 0 auto;
          max-width: 500px;
        }
      `}</style>
      <div className="container-narrow">
        <div className="masthead">
          <ul className="nav nav-pills pull-right">
            {/* Top right pills - empty in Django */}
          </ul>
          <h3 className="muted"><a href="/" className="muted">CloudPebble</a></h3>
        </div>
        <div className="row-fluid">
          <div className="span12 well">
            {error && (
              <div className="alert alert-error">{error}</div>
            )}
            <form className="form-horizontal" onSubmit={handleSubmit} style={{ marginBottom: 0 }}>
              <div className="control-group">
                <label className="control-label"><label htmlFor="id_username">Username:</label></label>
                <div className="controls">
                  <input 
                    id="id_username" 
                    maxLength={254} 
                    name="username" 
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
              </div>
              <div className="control-group">
                <label className="control-label"><label htmlFor="id_password">Password:</label></label>
                <div className="controls">
                  <input 
                    id="id_password" 
                    name="password" 
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
              </div>
              <div className="form-actions" style={{ marginBottom: 0, paddingBottom: 0 }}>
                <p>
                  <button className="btn btn-primary" type="submit" disabled={loading}>
                    {loading ? 'Logging in...' : 'Log in'}
                  </button>
                </p>
                <p style={{ marginBottom: 0 }}>
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
