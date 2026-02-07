'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from './ProjectList.module.css';

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

// Build states from Django
const BUILD_STATES = {
  WAITING: 0,
  RUNNING: 1,
  SUCCEEDED: 2,
  FAILED: 3,
};

function formatDate(date: Date | string): string {
  const d = new Date(date);
  return d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).replace(',', ' –');
}

function getBuildLabel(state: number): { text: string; className: string } {
  switch (state) {
    case BUILD_STATES.SUCCEEDED:
      return { text: 'Successful', className: styles.labelSuccess };
    case BUILD_STATES.FAILED:
      return { text: 'Failed', className: styles.labelError };
    default:
      return { text: 'Pending', className: styles.labelInfo };
  }
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
        router.push(`/ide/project/${data.id}`);
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
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <h1 className={styles.logo}>
          <span className={styles.logoCloud}>Cloud</span>
          <span className={styles.logoPebble}>Pebble</span>
        </h1>
        <ul className={styles.navPills}>
          <li><a className={`${styles.btn} ${styles.active}`}>Projects</a></li>
          <li><a href="/ide/settings" className={styles.btn}>Settings</a></li>
          <li><button onClick={handleLogout} className={styles.btn}>Sign out</button></li>
        </ul>
      </div>

      {/* Content */}
      <div className={styles.content}>
        <div className={styles.projectListHeader}>
          <h2 className={styles.sectionHeading}>All your projects</h2>
          <p className={styles.buttons}>
            <button 
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={() => setShowCreateModal(true)}
            >
              Create
            </button>
            <button 
              className={styles.btn}
              onClick={() => setShowImportModal(true)}
            >
              Import
            </button>
          </p>
        </div>

        {projects.length > 0 ? (
          <div className={styles.well}>
            <table className={styles.table}>
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
                    <td className={styles.projectName}>
                      <a href={`/ide/project/${project.id}`}>{project.name}</a>
                    </td>
                    <td className={styles.projectLastModified}>
                      {formatDate(project.updated_at)}
                    </td>
                    <td className={styles.projectLastBuild}>
                      <span className={styles.muted}>Never</span>
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

      {/* Create Project Modal */}
      {showCreateModal && (
        <div className={styles.modalBackdrop} onClick={() => setShowCreateModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Create New Project</h3>
            </div>
            <div className={styles.modalBody}>
              {error && <div className={styles.alertError}>{error}</div>}
              <form className={styles.formHorizontal} onSubmit={handleCreateProject}>
                <div className={styles.controlGroup}>
                  <label className={styles.controlLabel}>Project name</label>
                  <div className={styles.controls}>
                    <input
                      type="text"
                      value={newProjectName}
                      onChange={(e) => setNewProjectName(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>
                </div>
                <div className={styles.controlGroup}>
                  <label className={styles.controlLabel}>Project type</label>
                  <div className={styles.controls}>
                    <select value={projectType} onChange={(e) => setProjectType(e.target.value)}>
                      <option value="native">Pebble C SDK</option>
                      <option value="package">Pebble Package</option>
                      <option value="rocky">Rocky.js (beta)</option>
                      <option value="pebblejs">Pebble.js (beta)</option>
                    </select>
                  </div>
                </div>
                <div className={styles.controlGroup}>
                  <label className={styles.controlLabel}>SDK Version</label>
                  <div className={styles.controls}>
                    <select value={sdkVersion} onChange={(e) => setSdkVersion(e.target.value)}>
                      <option value="2">SDK 2</option>
                      <option value="3">SDK 4</option>
                    </select>
                  </div>
                </div>
              </form>
            </div>
            <div className={styles.modalFooter}>
              <button 
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={handleCreateProject}
                disabled={creating}
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button 
                className={styles.btn}
                onClick={() => setShowCreateModal(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Import Modal (shimmed for now) */}
      {showImportModal && (
        <div className={styles.modalBackdrop} onClick={() => setShowImportModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Import Existing Project</h3>
            </div>
            <div className={styles.modalBody}>
              <p>Import functionality coming soon.</p>
            </div>
            <div className={styles.modalFooter}>
              <button 
                className={styles.btn}
                onClick={() => setShowImportModal(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
