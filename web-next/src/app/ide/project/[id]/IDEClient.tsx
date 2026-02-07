'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import './ide.css';

// CodeMirror imports
import { EditorState } from '@codemirror/state';
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { javascript } from '@codemirror/lang-javascript';
import { json } from '@codemirror/lang-json';
import { cpp } from '@codemirror/lang-cpp';
import { oneDark } from '@codemirror/theme-one-dark';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import { autocompletion, closeBrackets } from '@codemirror/autocomplete';
import { bracketMatching, foldGutter } from '@codemirror/language';

interface SourceFile {
  id: number;
  name: string;
  target: string;
  file_path: string;
  lastModified: number;
}

interface Resource {
  id: number;
  file_name: string;
  kind: string;
  identifiers: string[];
}

interface ProjectInfo {
  type: string;
  name: string;
  app_uuid: string;
  sdk_version: string;
  source_files: SourceFile[];
  resources: Resource[];
}

interface Project {
  id: number;
  name: string;
  project_type: string;
  app_uuid: string;
}

interface Props {
  project: Project;
}

// Target display names
const TARGET_NAMES: Record<string, string> = {
  app: 'App Source',
  public: 'Public headers',
  pkjs: 'PebbleKit JS',
  worker: 'Worker source',
  common: 'Shared JavaScript',
};

export default function IDEClient({ project }: Props) {
  const router = useRouter();
  const [projectInfo, setProjectInfo] = useState<ProjectInfo | null>(null);
  const [activePane, setActivePane] = useState<string>('settings');
  const [activeFile, setActiveFile] = useState<SourceFile | null>(null);
  const [fileContent, setFileContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [showEmulator, setShowEmulator] = useState(false);
  const [showNewFileModal, setShowNewFileModal] = useState(false);
  const [newFileName, setNewFileName] = useState('');
  const [newFileType, setNewFileType] = useState('c');
  const [newFileTarget, setNewFileTarget] = useState('app');

  const editorRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView | null>(null);

  // Load project info
  useEffect(() => {
    async function loadProjectInfo() {
      try {
        const response = await fetch(`/api/projects/${project.id}/info`);
        if (response.ok) {
          const data = await response.json();
          setProjectInfo(data);
        }
      } catch (error) {
        console.error('Failed to load project info:', error);
      } finally {
        setIsLoading(false);
      }
    }
    loadProjectInfo();
  }, [project.id]);

  // Get language extension based on file name
  const getLanguageExtension = (fileName: string) => {
    if (fileName.endsWith('.js')) return javascript();
    if (fileName.endsWith('.json')) return json();
    if (fileName.endsWith('.c') || fileName.endsWith('.h')) return cpp();
    return cpp(); // Default to C
  };

  // Initialize/update CodeMirror
  useEffect(() => {
    if (!editorRef.current || !activeFile) return;

    // Destroy existing editor
    if (editorViewRef.current) {
      editorViewRef.current.destroy();
    }

    const extensions = [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      history(),
      foldGutter(),
      bracketMatching(),
      closeBrackets(),
      autocompletion(),
      highlightSelectionMatches(),
      keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap]),
      getLanguageExtension(activeFile.name),
      oneDark,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          setHasUnsavedChanges(true);
        }
      }),
      // Ctrl+S / Cmd+S to save
      keymap.of([{
        key: 'Mod-s',
        run: () => {
          handleSaveFile();
          return true;
        }
      }]),
    ];

    const state = EditorState.create({
      doc: fileContent,
      extensions,
    });

    const view = new EditorView({
      state,
      parent: editorRef.current,
    });

    editorViewRef.current = view;

    return () => {
      view.destroy();
    };
  }, [activeFile, fileContent]);

  // Load file content
  const handleOpenFile = async (file: SourceFile) => {
    if (hasUnsavedChanges) {
      if (!confirm('You have unsaved changes. Discard them?')) {
        return;
      }
    }

    setActivePane('editor');
    setActiveFile(file);
    setHasUnsavedChanges(false);

    try {
      const response = await fetch(`/api/projects/${project.id}/source/${file.id}`);
      if (response.ok) {
        const data = await response.json();
        setFileContent(data.source);
      }
    } catch (error) {
      console.error('Failed to load file:', error);
    }
  };

  // Save file
  const handleSaveFile = useCallback(async () => {
    if (!activeFile || !editorViewRef.current) return;

    setIsSaving(true);
    const content = editorViewRef.current.state.doc.toString();

    try {
      const response = await fetch(`/api/projects/${project.id}/source/${activeFile.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });

      if (response.ok) {
        setHasUnsavedChanges(false);
      } else {
        alert('Failed to save file');
      }
    } catch (error) {
      console.error('Failed to save file:', error);
      alert('Failed to save file');
    } finally {
      setIsSaving(false);
    }
  }, [activeFile, project.id]);

  // Create new file
  const handleCreateFile = async () => {
    let fileName = newFileName.trim();
    if (!fileName) {
      alert('Please enter a file name');
      return;
    }

    // Add extension if not present
    if (newFileType === 'c' && !fileName.endsWith('.c') && !fileName.endsWith('.h')) {
      fileName += '.c';
    } else if (newFileType === 'js' && !fileName.endsWith('.js')) {
      fileName += '.js';
    } else if (newFileType === 'json' && !fileName.endsWith('.json')) {
      fileName += '.json';
    }

    try {
      const response = await fetch(`/api/projects/${project.id}/source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: fileName,
          target: newFileTarget,
          content: '',
        }),
      });

      if (response.ok) {
        const data = await response.json();
        // Reload project info to get updated file list
        const infoResponse = await fetch(`/api/projects/${project.id}/info`);
        if (infoResponse.ok) {
          const info = await infoResponse.json();
          setProjectInfo(info);
        }
        setShowNewFileModal(false);
        setNewFileName('');
        // Open the new file
        handleOpenFile(data.file);
      } else {
        const error = await response.json();
        alert(error.error || 'Failed to create file');
      }
    } catch (error) {
      console.error('Failed to create file:', error);
      alert('Failed to create file');
    }
  };

  // Delete file
  const handleDeleteFile = async (file: SourceFile) => {
    if (!confirm(`Are you sure you want to delete ${file.name}?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/projects/${project.id}/source/${file.id}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        // Reload project info
        const infoResponse = await fetch(`/api/projects/${project.id}/info`);
        if (infoResponse.ok) {
          const info = await infoResponse.json();
          setProjectInfo(info);
        }
        // Clear editor if this was the active file
        if (activeFile?.id === file.id) {
          setActiveFile(null);
          setActivePane('settings');
        }
      }
    } catch (error) {
      console.error('Failed to delete file:', error);
    }
  };

  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    router.push('/accounts/login');
  };

  // Group source files by target
  const groupedFiles: Record<string, SourceFile[]> = {};
  if (projectInfo) {
    for (const file of projectInfo.source_files) {
      const target = file.target || 'app';
      if (!groupedFiles[target]) {
        groupedFiles[target] = [];
      }
      groupedFiles[target].push(file);
    }
  }

  if (isLoading) {
    return (
      <div className="main-container">
        <div id="progress-pane">
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
    );
  }

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
                  <ul className="nav-list" id="sidebar-sources">
                    {Object.entries(groupedFiles).map(([target, files]) => (
                      <li key={target}>
                        <span className="nav-header">{TARGET_NAMES[target] || target}</span>
                        <button 
                          className="btn btn-small" 
                          onClick={() => {
                            setNewFileTarget(target);
                            setShowNewFileModal(true);
                          }}
                        >
                          Add new
                        </button>
                        <ul className="nav-list">
                          {files.map(file => (
                            <li 
                              key={file.id}
                              id={`sidebar-pane-source-${file.id}`}
                              className={activeFile?.id === file.id ? 'active' : ''}
                            >
                              <a 
                                href="#" 
                                onClick={(e) => { e.preventDefault(); handleOpenFile(file); }}
                              >
                                {file.name}{' '}
                                {hasUnsavedChanges && activeFile?.id === file.id && (
                                  <i className="icon-asterisk" style={{ fontSize: '8px' }}></i>
                                )}
                              </a>
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                    {Object.keys(groupedFiles).length === 0 && (
                      <li>
                        <span className="nav-header">App Source</span>
                        <button 
                          className="btn btn-small" 
                          onClick={() => {
                            setNewFileTarget('app');
                            setShowNewFileModal(true);
                          }}
                        >
                          Add new
                        </button>
                      </li>
                    )}
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
                      {projectInfo?.resources.map(resource => (
                        <li key={resource.id} id={`sidebar-pane-resource-${resource.id}`}>
                          <a href="#">{resource.file_name}</a>
                        </li>
                      ))}
                    </ul>
                  </li>
                )}
              </ul>
            </div>
          </div>

          {/* Main pane */}
          <div id="pane-parent">
            <div id="main-pane">
              {/* Editor pane */}
              {activePane === 'editor' && activeFile && (
                <div className="pane-content" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <div style={{ padding: '5px 10px', borderBottom: '1px solid #ccc', background: '#f5f5f5', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>
                      <strong>{activeFile.name}</strong>
                      {hasUnsavedChanges && <span style={{ color: '#999' }}> (unsaved)</span>}
                    </span>
                    <div>
                      <button 
                        className="btn btn-small btn-primary" 
                        onClick={handleSaveFile}
                        disabled={isSaving || !hasUnsavedChanges}
                      >
                        {isSaving ? 'Saving...' : 'Save'}
                      </button>
                      <button 
                        className="btn btn-small btn-danger" 
                        onClick={() => handleDeleteFile(activeFile)}
                        style={{ marginLeft: '5px' }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                  <div ref={editorRef} style={{ flex: 1, overflow: 'auto' }}></div>
                </div>
              )}

              {/* Settings pane */}
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
          </div>
        </div>
      </div>

      {/* New File Modal */}
      {showNewFileModal && (
        <div className="modal-backdrop fade in" onClick={() => setShowNewFileModal(false)}></div>
      )}
      <div id="editor-new-file-prompt" className={`modal fade ${showNewFileModal ? 'in' : 'hide'}`} style={{ display: showNewFileModal ? 'block' : 'none' }} tabIndex={-1} role="dialog">
        <div className="modal-header">
          <h3>Create new file</h3>
        </div>
        <form className="form-horizontal" onSubmit={(e) => { e.preventDefault(); handleCreateFile(); }}>
          <div className="modal-body">
            <div className="control-group">
              <label className="control-label" htmlFor="new-file-type">File type</label>
              <div className="controls">
                <select 
                  id="new-file-type" 
                  value={newFileType}
                  onChange={(e) => setNewFileType(e.target.value)}
                >
                  <option value="c">C file</option>
                  <option value="js">JavaScript file</option>
                  <option value="json">JSON file</option>
                </select>
              </div>
            </div>
            <div className="control-group">
              <label className="control-label" htmlFor="new-file-name">Filename</label>
              <div className="controls">
                <input 
                  type="text" 
                  id="new-file-name"
                  value={newFileName}
                  onChange={(e) => setNewFileName(e.target.value)}
                  placeholder={newFileType === 'c' ? 'main.c' : newFileType === 'js' ? 'app.js' : 'config.json'}
                />
              </div>
            </div>
            {project.project_type !== 'simplyjs' && project.project_type !== 'pebblejs' && (
              <div className="control-group">
                <label className="control-label" htmlFor="new-file-target">Target</label>
                <div className="controls">
                  <select 
                    id="new-file-target"
                    value={newFileTarget}
                    onChange={(e) => setNewFileTarget(e.target.value)}
                  >
                    <option value="app">
                      {project.project_type === 'package' ? 'Private source' : 'App / Watchface'}
                    </option>
                    {project.project_type === 'native' && (
                      <option value="worker">Background worker</option>
                    )}
                    {project.project_type === 'package' && (
                      <option value="public">Public header file</option>
                    )}
                    <option value="pkjs">PebbleKit JS</option>
                  </select>
                </div>
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn" onClick={() => setShowNewFileModal(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary">Create</button>
          </div>
        </form>
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
