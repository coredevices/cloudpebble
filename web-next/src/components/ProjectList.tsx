'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import './ProjectList.css';

interface Project {
  id: number;
  name: string;
  updated_at: string;
}

interface User {
  id: number;
  username: string;
}

interface Props {
  projects: Project[];
  user: User;
}

function formatDate(date: string): string {
  const d = new Date(date);
  return d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).replace(',', ' –');
}

export default function ProjectList({ projects, user }: Props) {
  const router = useRouter();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [projectType, setProjectType] = useState('native');
  const [sdkVersion, setSdkVersion] = useState('3');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    router.push('/accounts/login');
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError('');

    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newProjectName,
          project_type: projectType,
          sdk_version: sdkVersion,
        }),
      });

      const data = await res.json();

      if (res.ok) {
        router.push(`/ide/project/${data.project.id}`);
      } else {
        setError(data.error || 'Failed to create project');
      }
    } catch {
      setError('An error occurred');
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <div className="main-container">
        {/* Header */}
        <div className="header">
          <div className="container">
            <h1 className="cloudpebble-logo">
              <span className="cloudpebble-logo-cloud">CLOUD</span>
              <span className="cloudpebble-logo-pebble">PEBBLE</span>
            </h1>
            <ul className="nav-pills header-right">
              <li><a className="btn active">PROJECTS</a></li>
              <li><a href="/ide/settings" className="btn">SETTINGS</a></li>
              <li><button onClick={handleLogout} className="btn">SIGN OUT</button></li>
            </ul>
          </div>
        </div>

        {/* Content */}
        <div className="narrow-container container">
          <div className="project-list-header">
            <h2 className="section-heading">ALL YOUR PROJECTS</h2>
            <p className="buttons">
              <button 
                className="btn btn-primary"
                onClick={() => setShowCreateModal(true)}
              >
                CREATE
              </button>
              <button 
                className="btn"
                onClick={() => setShowImportModal(true)}
              >
                IMPORT
              </button>
            </p>
          </div>

          {projects.length > 0 ? (
            <div className="well">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ minWidth: 180 }}>Project</th>
                    <th>Last modified</th>
                    <th>Last built</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((project) => (
                    <tr key={project.id}>
                      <td className="project-name">
                        <a href={`/ide/project/${project.id}`}>{project.name}</a>
                      </td>
                      <td className="project-last-modified">
                        {formatDate(project.updated_at)}
                      </td>
                      <td className="project-last-build">
                        <span className="muted">Never</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>You don&apos;t have any projects yet.</p>
          )}
        </div>

        {/* Footer */}
        <div className="footer">
          <div className="container">
            <p className="small-print">
              CloudPebble was created by Katharine Berry and is now run by Pebble.<br/>
              Questions? Email us at <a href="mailto:cloudpebble@getpebble.com">cloudpebble@getpebble.com</a>. 
              See our <a href="https://getpebble.com/legal/cookies/">cookie</a> and <a href="https://getpebble.com/legal/privacy/">privacy</a> policies.
            </p>
          </div>
        </div>
      </div>

      {/* Create Project Modal */}
      {showCreateModal && (
        <>
          <div className="modal-backdrop in" onClick={() => setShowCreateModal(false)} />
          <div className="modal fade in">
            <div className="modal-header">
              <h3>CREATE NEW PROJECT</h3>
            </div>
            <div className="modal-body">
              {error && <div className="alert alert-error">{error}</div>}
              <form className="form-horizontal">
                <div className="control-group">
                  <label className="control-label">PROJECT NAME</label>
                  <div className="controls">
                    <input
                      type="text"
                      value={newProjectName}
                      onChange={(e) => setNewProjectName(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>
                </div>
                <div className="control-group">
                  <label className="control-label">PROJECT TYPE</label>
                  <div className="controls">
                    <select value={projectType} onChange={(e) => setProjectType(e.target.value)}>
                      <option value="native">Pebble C SDK</option>
                      <option value="package">Pebble Package</option>
                      <option value="rocky">Rocky.js (beta)</option>
                      <option value="pebblejs">Pebble.js (beta)</option>
                    </select>
                  </div>
                </div>
                <div className="control-group">
                  <label className="control-label">SDK VERSION</label>
                  <div className="controls">
                    <select value={sdkVersion} onChange={(e) => setSdkVersion(e.target.value)}>
                      <option value="2">SDK 2</option>
                      <option value="3">SDK 4</option>
                    </select>
                  </div>
                </div>
              </form>
            </div>
            <div className="modal-footer">
              <button 
                className="btn btn-primary"
                onClick={handleCreateProject}
                disabled={creating}
              >
                {creating ? 'CREATING...' : 'CREATE'}
              </button>
              <button 
                className="btn"
                onClick={() => setShowCreateModal(false)}
              >
                CANCEL
              </button>
            </div>
          </div>
        </>
      )}

      {/* Import Modal */}
      {showImportModal && (
        <>
          <div className="modal-backdrop in" onClick={() => setShowImportModal(false)} />
          <div className="modal fade in">
            <div className="modal-header">
              <h3>IMPORT EXISTING PROJECT</h3>
            </div>
            <div className="modal-body">
              <p>Import functionality coming soon.</p>
            </div>
            <div className="modal-footer">
              <button 
                className="btn"
                onClick={() => setShowImportModal(false)}
              >
                CLOSE
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
