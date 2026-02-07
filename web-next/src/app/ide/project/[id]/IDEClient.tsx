'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import './ide.css';

interface Project {
  id: number;
  name: string;
  project_type: string;
  app_uuid: string;
}

interface Props {
  project: Project;
}

export default function IDEClient({ project }: Props) {
  const router = useRouter();
  const [activePane, setActivePane] = useState<string>('settings');
  const [showEmulator, setShowEmulator] = useState(false);

  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    router.push('/accounts/login');
  };

  return (
    <div className="main-container">
      {/* Header - from project.html */}
      <div className="header">
        <h1 className="cloudpebble-logo" style={{ paddingLeft: 40 }}>
          <span className="cloudpebble-logo-cloud">Cloud</span>
          <span className="cloudpebble-logo-pebble">Pebble</span>
        </h1>
        <div className="header-right">
          <ul className="nav-pills">
            <li>
              <a href="https://developer.getpebble.com/" target="_blank" className="btn">
                Documentation
              </a>
            </li>
            <li>
              <a href="/ide/" className="btn">Projects</a>
            </li>
            <li>
              <a href="/ide/settings" className="btn">Settings</a>
            </li>
            <li>
              <a href="#" onClick={(e) => { e.preventDefault(); handleLogout(); }} className="btn">
                Sign out
              </a>
            </li>
          </ul>
        </div>
      </div>

      {/* Project container */}
      <div className="project-container">
        <div className="row-fluid">
          {/* Sidebar */}
          <div id="sidebar-wrapper">
            <div>
              {/* Emulator container */}
              <div id="emulator-container" style={{ display: showEmulator ? 'block' : 'none' }}>
                <canvas width="144" height="168"></canvas>
                <div className="up qemu-button"></div>
                <div className="down qemu-button"></div>
                <div className="back qemu-button"></div>
                <div className="select qemu-button"></div>
                <img src="/ide/img/configure.png" className="configure" alt="Configure" />
              </div>

              {/* Navigation sidebar */}
              <ul className={`nav-list ${showEmulator ? 'with-emulator' : ''}`} id="sidebar">
                <li className="nav-header project-name">{project.name}</li>
                <li 
                  className={`nav-header ${activePane === 'settings' ? 'active' : ''}`} 
                  id="sidebar-pane-settings"
                  onClick={() => setActivePane('settings')}
                >
                  <a href="#">Settings</a>
                </li>
                {(project.project_type === 'native' || project.project_type === 'package') && (
                  <li 
                    className={`nav-header sdk3-only ${activePane === 'timeline' ? 'active' : ''}`}
                    id="sidebar-pane-timeline"
                    onClick={() => setActivePane('timeline')}
                  >
                    <a href="#">Timeline (Preview)</a>
                  </li>
                )}
                <li 
                  className={`nav-header ${activePane === 'compile' ? 'active' : ''}`}
                  id="sidebar-pane-compile"
                  onClick={() => setActivePane('compile')}
                >
                  <a href="#">Compilation</a>
                </li>
                {(project.project_type === 'package' || project.project_type === 'native') && (
                  <li 
                    className={`nav-header sdk3-only ${activePane === 'dependencies' ? 'active' : ''}`}
                    id="sidebar-pane-dependencies"
                    onClick={() => setActivePane('dependencies')}
                  >
                    <a href="#">Dependencies</a>
                    <span className="spinner spinner-dark hide"></span>
                  </li>
                )}
                <li 
                  className={`nav-header disabled ${activePane === 'github' ? 'active' : ''}`}
                  id="sidebar-pane-github"
                  onClick={() => setActivePane('github')}
                >
                  <a href="#">GitHub</a>
                </li>

                {/* Source files section */}
                <li className="nav-section">
                  <span className="nav-header">Source Files</span>
                  <button 
                    className="btn btn-small" 
                    id="sidebar-pane-new-file"
                    onClick={() => {/* TODO: Show new file modal */}}
                  >
                    Add new
                  </button>
                  <ul className="nav-list" id="sidebar-sources">
                    {/* Source files will be listed here */}
                  </ul>
                </li>

                {/* Resources section */}
                {project.project_type !== 'simplyjs' && project.project_type !== 'rocky' && (
                  <li className="nav-section">
                    <span className="nav-header">Resources</span>
                    <button 
                      className="btn btn-small" 
                      id="sidebar-pane-new-resource"
                      onClick={() => {/* TODO: Show new resource modal */}}
                    >
                      Add new
                    </button>
                    <ul className="nav-list" id="sidebar-resources">
                      {/* Resources will be listed here */}
                    </ul>
                  </li>
                )}
              </ul>
            </div>
          </div>

          {/* Main pane */}
          <div id="pane-parent">
            <div id="main-pane">
              {/* Content panes */}
              {activePane === 'settings' && (
                <div className="pane-content">
                  <h2>Project Settings</h2>
                  <p>Project: {project.name}</p>
                  <p>Type: {project.project_type}</p>
                  <p>UUID: {project.app_uuid}</p>
                </div>
              )}
              {activePane === 'compile' && (
                <div className="pane-content">
                  <h2>Compilation</h2>
                  <p>Build functionality coming soon.</p>
                  <button className="btn btn-primary" onClick={() => setShowEmulator(true)}>
                    Run Build
                  </button>
                </div>
              )}
              {activePane === 'github' && (
                <div className="pane-content">
                  <h2>GitHub</h2>
                  <p>GitHub integration coming soon.</p>
                </div>
              )}
              {activePane === 'dependencies' && (
                <div className="pane-content">
                  <h2>Dependencies</h2>
                  <p>NPM package management coming soon.</p>
                </div>
              )}
              {activePane === 'timeline' && (
                <div className="pane-content">
                  <h2>Timeline (Preview)</h2>
                  <p>Timeline functionality coming soon.</p>
                </div>
              )}
            </div>
            <div id="progress-pane" style={{ display: 'none' }}>
              <div className="row-fluid">
                <div className="offset2 span8">
                  <div style={{ marginTop: 200 }}>
                    <div className="progress progress-striped active">
                      <div className="bar" style={{ width: '100%' }}></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="footer">
        <p className="small-print">
          Questions? Email us at <a href="mailto:cloudpebble@getpebble.com">cloudpebble@getpebble.com</a>.
          See our <a href="https://getpebble.com/legal/cookies/" target="_blank">cookie</a> and{' '}
          <a href="https://getpebble.com/legal/privacy/" target="_blank">privacy</a> policies.
        </p>
        <div className="pebble-logo">
          <div className="footer-credits hide">
            <span className="katharine-at">Katharine @</span>
            <a href="http://pbldev.io" target="_blank">
              <img src="/images/pebble.png" alt="Pebble" />
            </a>
          </div>
          <div className="prepare-autocomplete katharine-at">Preparing autocomplete…</div>
        </div>
        <div className="lang-select project-page">
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
  );
}
