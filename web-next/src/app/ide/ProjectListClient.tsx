'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import '../common.css';
import './project-list.css';

interface Project {
  id: number;
  name: string;
  updated_at: string;
  last_build?: string | null;
}

interface Props {
  projects: Project[];
}

// Django date format: "j F, 'y – H:i" e.g. "7 February, '26 – 00:55"
function formatDate(date: string): string {
  const d = new Date(date);
  const day = d.getDate();
  const month = d.toLocaleDateString('en-GB', { month: 'long' });
  const year = d.getFullYear().toString().slice(-2);
  const hours = d.getHours().toString().padStart(2, '0');
  const minutes = d.getMinutes().toString().padStart(2, '0');
  return `${day} ${month}, '${year} – ${hours}:${minutes}`;
}

export default function ProjectListClient({ projects }: Props) {
  const router = useRouter();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [activeImportTab, setActiveImportTab] = useState<'zip' | 'github'>('zip');
  const [newProjectName, setNewProjectName] = useState('');
  const [projectType, setProjectType] = useState('native');
  const [sdkVersion, setSdkVersion] = useState('3');
  const [template, setTemplate] = useState('0');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    router.push('/accounts/login');
  };

  const handleCreateProject = async () => {
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
          template: template,
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
    <div className="main-container">
      {/* Header - from base-narrow.html */}
      <div className="header">
        <div className="container">
          <h1 className="cloudpebble-logo">
            <span className="cloudpebble-logo-cloud">Cloud</span>
            <span className="cloudpebble-logo-pebble">Pebble</span>
          </h1>
          <div className="header-right">
            {/* headercontent block from index.html */}
            <ul className="nav-pills">
              <li><a className="active btn">Projects</a></li>
              <li><a href="/ide/settings" className="btn">Settings</a></li>
              <li><a href="#" onClick={(e) => { e.preventDefault(); handleLogout(); }} className="btn">Sign out</a></li>
            </ul>
          </div>
        </div>
      </div>

      {/* narrowcontent block */}
      <div className="container narrow-container">
        <div className="project-list-header">
          <h2 className="section-heading">All your projects</h2>
          <p className="buttons">
            <button id="create-project" className="btn btn-primary" onClick={() => setShowCreateModal(true)}>Create</button>
            <button id="import-project" className="btn" onClick={() => setShowImportModal(true)}>Import</button>
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
                    <td className="project-last-modified">{formatDate(project.updated_at)}</td>
                    <td className="project-last-build">
                      {project.last_build ? (
                        <>
                          {formatDate(project.last_build)}
                          <span className="label label-success">Successful</span>
                        </>
                      ) : (
                        <span className="muted">Never</span>
                      )}
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

      {/* Footer - from base-narrow.html */}
      <div className="footer">
        <div className="container">
          <p className="small-print">
            CloudPebble was created by Katharine Berry and is now run by Pebble.
            <br />
            Questions? Email us at <a href="mailto:cloudpebble@getpebble.com">cloudpebble@getpebble.com</a>.
            See our <a href="https://getpebble.com/legal/cookies/" target="_blank">cookie</a> and{' '}
            <a href="https://getpebble.com/legal/privacy/" target="_blank">privacy</a> policies.
          </p>
          <div className="pebble-logo">
            <a href="http://pbldev.io/" target="_blank">
              <img src="/images/pebble.png" alt="Pebble" />
            </a>
          </div>
          <div className="lang-select">
            <select name="language" defaultValue="en">
              <option value="en">English</option>
              <option value="es">español</option>
              <option value="fr">français</option>
              <option value="de">Deutsch</option>
              <option value="zh-hans">简体中文</option>
              <option value="zh-hant">繁體中文</option>
            </select>
          </div>
        </div>
      </div>

      {/* Create Project Modal - from index.html */}
      {showCreateModal && (
        <>
          <div className="modal-backdrop in" onClick={() => setShowCreateModal(false)} />
          <div id="project-prompt" className="modal fade in" tabIndex={-1} role="dialog">
            <div className="modal-header">
              <h3 id="project-prompt-title">Create New Project</h3>
            </div>
            <div className="modal-body">
              {error && <div id="project-prompt-errors" className="alert alert-error">{error}</div>}
              <form className="form-horizontal">
                <div className="control-group">
                  <label className="control-label" htmlFor="project-prompt-value">Project name</label>
                  <div className="controls">
                    <input 
                      type="text" 
                      id="project-prompt-value"
                      value={newProjectName}
                      onChange={(e) => setNewProjectName(e.target.value)}
                      autoFocus
                    />
                  </div>
                </div>
                <div className="control-group project-type-holder">
                  <label className="control-label" htmlFor="project-type">Project type</label>
                  <div className="controls">
                    <select id="project-type" value={projectType} onChange={(e) => setProjectType(e.target.value)}>
                      <option value="native">Pebble C SDK</option>
                      <option value="package">Pebble Package</option>
                      <option value="rocky">Rocky.js (beta)</option>
                      <option value="pebblejs">Pebble.js (beta)</option>
                      <option value="simplyjs" disabled>Simply.js</option>
                    </select>
                  </div>
                </div>
                <div className="sdk-version control-group">
                  <label className="control-label" htmlFor="project-sdk-version">SDK Version</label>
                  <div className="controls">
                    <select id="project-sdk-version" value={sdkVersion} onChange={(e) => setSdkVersion(e.target.value)}>
                      <option value="2">SDK 2</option>
                      <option value="3">SDK 4</option>
                    </select>
                  </div>
                </div>
                <div className="control-group" id="template-holder">
                  <label className="control-label" htmlFor="project-template">Template</label>
                  <div className="controls">
                    <select id="project-template" value={template} onChange={(e) => setTemplate(e.target.value)}>
                      <option value="0">Empty project</option>
                    </select>
                  </div>
                </div>
              </form>
            </div>
            <div className="modal-footer">
              <button className="btn btn-primary" id="project-confirm-button" onClick={handleCreateProject} disabled={creating}>
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button className="btn" onClick={() => setShowCreateModal(false)}>Cancel</button>
            </div>
          </div>
        </>
      )}

      {/* Import Modal - from index.html */}
      {showImportModal && (
        <>
          <div className="modal-backdrop in" onClick={() => setShowImportModal(false)} />
          <div id="import-prompt" className="modal fade in" tabIndex={-1} role="dialog">
            <div className="modal-header">
              <h3>Import Existing Project</h3>
            </div>
            <div className="modal-body">
              <ul className="nav nav-tabs">
                <li className={activeImportTab === 'zip' ? 'active' : ''}>
                  <a href="#import-zip" onClick={(e) => { e.preventDefault(); setActiveImportTab('zip'); }}>Upload Zip</a>
                </li>
                <li className={activeImportTab === 'github' ? 'active' : ''}>
                  <a href="#import-github" onClick={(e) => { e.preventDefault(); setActiveImportTab('github'); }}>Import from GitHub</a>
                </li>
              </ul>
              <div className="tab-content">
                <div id="import-zip" className={`tab-pane ${activeImportTab === 'zip' ? 'active' : ''}`}>
                  <div className="errors alert alert-error hide"></div>
                  <form className="form-horizontal">
                    <div className="control-group">
                      <label className="control-label" htmlFor="import-zip-name">Project name</label>
                      <div className="controls">
                        <input type="text" id="import-zip-name" />
                      </div>
                    </div>
                    <div className="control-group">
                      <label className="control-label">Zip file</label>
                      <div className="controls">
                        <input type="file" accept="application/zip,application/x-zip-compressed" />
                        <span className="help-block">This must be a zip file containing a standard Pebble project.</span>
                      </div>
                    </div>
                  </form>
                </div>
                <div id="import-github" className={`tab-pane ${activeImportTab === 'github' ? 'active' : ''}`}>
                  <div className="errors alert alert-error hide"></div>
                  <form className="form-horizontal">
                    <div className="control-group">
                      <label className="control-label" htmlFor="import-github-name">Project name</label>
                      <div className="controls">
                        <input type="text" id="import-github-name" />
                      </div>
                    </div>
                    <div className="control-group">
                      <label className="control-label" htmlFor="import-github-url">GitHub Project</label>
                      <div className="controls">
                        <input 
                          className="span4" 
                          type="text" 
                          id="import-github-url" 
                          placeholder="github.com/Katharine/pebble-stopwatch"
                        />
                      </div>
                    </div>
                    <div className="control-group">
                      <label className="control-label" htmlFor="import-github-branch">Branch (optional)</label>
                      <div className="controls">
                        <input type="text" id="import-github-branch" placeholder="master" />
                      </div>
                    </div>
                  </form>
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-primary" id="run-import">Import</button>
              <button className="btn" onClick={() => setShowImportModal(false)}>Cancel</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
