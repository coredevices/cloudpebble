'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
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
      setError('An error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="main-container">
      <style jsx global>{`
        body {
          background-color: #1a1a1a;
          color: #fff;
          font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
          margin: 0;
          padding: 0;
        }
        .container-narrow {
          margin: 0 auto;
          max-width: 500px;
          padding-top: 60px;
        }
        .masthead {
          margin-bottom: 20px;
        }
        .masthead h3 {
          margin: 0;
        }
        .masthead h3 a {
          color: #999;
          text-decoration: none;
        }
        .masthead h3 a:hover {
          color: #fff;
        }
        .well {
          background-color: #333;
          border-radius: 8px;
          padding: 20px;
        }
        .form-horizontal .control-group {
          margin-bottom: 15px;
        }
        .control-label {
          display: block;
          margin-bottom: 5px;
          color: #999;
        }
        .controls input {
          width: 100%;
          padding: 8px 12px;
          border: 1px solid #555;
          border-radius: 4px;
          background: #222;
          color: #fff;
          font-size: 14px;
          box-sizing: border-box;
        }
        .controls input:focus {
          outline: none;
          border-color: #0088cc;
        }
        .form-actions {
          margin-top: 20px;
        }
        .btn {
          padding: 8px 16px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
        }
        .btn-primary {
          background-color: #0088cc;
          color: #fff;
        }
        .btn-primary:hover {
          background-color: #0077b3;
        }
        .btn-primary:disabled {
          background-color: #666;
          cursor: not-allowed;
        }
        .alert {
          padding: 10px 15px;
          border-radius: 4px;
          margin-bottom: 15px;
        }
        .alert-error {
          background-color: #c43c35;
          color: #fff;
        }
        a {
          color: #0088cc;
          text-decoration: none;
        }
        a:hover {
          text-decoration: underline;
        }
      `}</style>
      
      <div className="container-narrow">
        <div className="masthead">
          <h3 className="muted">
            <a href="/">CloudPebble</a>
          </h3>
        </div>
        <div className="row-fluid">
          <div className="span12 well">
            {error && (
              <div className="alert alert-error">
                {error}
              </div>
            )}
            
            <form className="form-horizontal" onSubmit={handleSubmit}>
              <div className="control-group">
                <label className="control-label">Username</label>
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
                <label className="control-label">Password</label>
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
                  <button 
                    className="btn btn-primary" 
                    type="submit"
                    disabled={loading}
                  >
                    {loading ? 'Logging in...' : 'Log in'}
                  </button>
                </p>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
