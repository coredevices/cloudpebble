# CloudPebble Next.js Rewrite - Detailed Plan

## Goal
Replace Django/nginx web frontend with Next.js on Vercel. **UI must be IDENTICAL to Django version** - copy HTML/CSS directly from Django templates.

## Source Reference
- Django templates: `cloudpebble/*/templates/`
- CSS: `cloudpebble/root/static/common/css/common.css`, `cloudpebble/ide/static/ide/css/`
- Original running at: https://obelisk-sweet.exe.xyz

---

## Pages

### 1. Authentication Pages
Source: `cloudpebble/auth/templates/registration/`

| Page | Template | Route | Status |
|------|----------|-------|--------|
| Login | `login.html` | `/accounts/login` | 🔄 In Progress |
| Registration | `registration_form.html` | `/accounts/register` | ⬜ Not Started |
| Password Reset | `password_reset_form.html` | `/accounts/password/reset` | ⬜ Not Started |
| Password Reset Done | `password_reset_done.html` | `/accounts/password/reset/done` | ⬜ Not Started |
| Password Reset Confirm | `password_reset_confirm.html` | `/accounts/password/reset/confirm` | ⬜ Not Started |
| Password Reset Complete | `password_reset_complete.html` | `/accounts/password/reset/complete` | ⬜ Not Started |
| Merge Account | `merge_account.html` | `/accounts/merge` | ⬜ Not Started |

### 2. Main Pages
Source: `cloudpebble/ide/templates/ide/`

| Page | Template | Route | Status |
|------|----------|-------|--------|
| Project List | `index.html` | `/ide/` | 🔄 In Progress |
| Project/IDE | `project.html` | `/ide/project/[id]` | ⬜ Not Started |
| User Settings | `settings.html` | `/ide/settings` | ⬜ Not Started |
| QEMU Config | `qemu-config.html` | `/ide/emulator/config` | ⬜ Not Started |
| QEMU Sensors | `qemu-sensors.html` | `/ide/emulator/sensors` | ⬜ Not Started |
| Enter Phone Token | `qemu-enter-token.html` | `/ide/emulator/token` | ⬜ Not Started |
| Gist Import | `gist-import.html` | `/ide/gist/[id]` | ⬜ Not Started |

### 3. IDE Sub-Panes (loaded dynamically in project.html)
Source: `cloudpebble/ide/templates/ide/project/`

| Pane | Template | Status |
|------|----------|--------|
| Compilation | `compile.html` | ⬜ Not Started |
| Project Settings | `settings.html` | ⬜ Not Started |
| GitHub Integration | `github.html` | ⬜ Not Started |
| Resources | `resource.html` | ⬜ Not Started |
| Timeline | `timeline.html` | ⬜ Not Started |
| Dependencies | `dependencies.html` | ⬜ Not Started |
| UI Editor | `ui-editor.html` | ⬜ Not Started |

---

## API Endpoints

### Authentication
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/auth/login` | POST | custom | ✅ Done |
| `/api/auth/logout` | POST | custom | ✅ Done |
| `/api/auth/register` | POST | registration | ⬜ Not Started |
| `/api/auth/password-reset` | POST | password_reset | ⬜ Not Started |

### Projects
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/projects` | GET | `get_projects` | ✅ Done |
| `/api/projects` | POST | `create_project` | 🔄 Partial |
| `/api/projects/[id]` | GET | `project_info` | ⬜ Not Started |
| `/api/projects/[id]` | DELETE | `delete_project` | ⬜ Not Started |
| `/api/projects/[id]/settings` | POST | `save_project_settings` | ⬜ Not Started |
| `/api/projects/[id]/dependencies` | POST | `save_project_dependencies` | ⬜ Not Started |
| `/api/projects/[id]/export` | POST | `begin_export` | ⬜ Not Started |

### Source Files
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/projects/[id]/source` | POST | `create_source_file` | ⬜ Not Started |
| `/api/projects/[id]/source/[fid]` | GET | `load_source_file` | ⬜ Not Started |
| `/api/projects/[id]/source/[fid]` | PUT | `save_source_file` | ⬜ Not Started |
| `/api/projects/[id]/source/[fid]` | DELETE | `delete_source_file` | ⬜ Not Started |
| `/api/projects/[id]/source/[fid]/rename` | POST | `rename_source_file` | ⬜ Not Started |
| `/api/projects/[id]/source/[fid]/is_safe` | GET | `source_file_is_safe` | ⬜ Not Started |

### Resources
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/projects/[id]/resource` | POST | `create_resource` | ⬜ Not Started |
| `/api/projects/[id]/resource/[rid]` | GET | `resource_info` | ⬜ Not Started |
| `/api/projects/[id]/resource/[rid]` | PUT | `update_resource` | ⬜ Not Started |
| `/api/projects/[id]/resource/[rid]` | DELETE | `delete_resource` | ⬜ Not Started |
| `/api/projects/[id]/resource/[rid]/[variant]` | GET | `show_resource` | ⬜ Not Started |
| `/api/projects/[id]/resource/[rid]/[variant]` | DELETE | `delete_variant` | ⬜ Not Started |

### Build
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/projects/[id]/build` | POST | `compile_project` | ⬜ Not Started |
| `/api/projects/[id]/build/last` | GET | `last_build` | ⬜ Not Started |
| `/api/projects/[id]/build/history` | GET | `build_history` | ⬜ Not Started |
| `/api/projects/[id]/build/[bid]/log` | GET | `build_log` | ⬜ Not Started |
| `/api/task/[id]` | GET | `check_task` | ⬜ Not Started |

### GitHub (SHIMMED - non-functional)
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/projects/[id]/github/repo` | POST | `set_project_repo` | ⬜ Shimmed |
| `/api/projects/[id]/github/repo/create` | POST | `create_project_repo` | ⬜ Shimmed |
| `/api/projects/[id]/github/commit` | POST | `github_push` | ⬜ Shimmed |
| `/api/projects/[id]/github/pull` | POST | `github_pull` | ⬜ Shimmed |

### Emulator
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/emulator/launch` | POST | `launch_emulator` | ⬜ Not Started |
| `/api/emulator/[id]/mobile_token` | GET | `generate_phone_token` | ⬜ Not Started |

### Import
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/import/zip` | POST | `import_zip` | ⬜ Not Started |
| `/api/import/github` | POST | `import_github` | ⬜ Not Started |
| `/api/import/gist` | POST | `do_import_gist` | ⬜ Not Started |

### Autocomplete (YCMD)
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/projects/[id]/autocomplete/init` | POST | `init_autocomplete` | ⬜ Not Started |

### NPM Packages
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/packages/search` | GET | `npm_search` | ⬜ Not Started |
| `/api/packages/info` | GET | `npm_info` | ⬜ Not Started |

### User
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/user/whats_new` | GET | `whats_new` | ⬜ Not Started |
| `/api/user/transition/accept` | POST | `transition_accept` | ⬜ Not Started |
| `/api/user/transition/export` | POST | `transition_export` | ⬜ Not Started |
| `/api/user/transition/delete` | POST | `transition_delete` | ⬜ Not Started |

### Settings
| Endpoint | Method | Django View | Status |
|----------|--------|-------------|--------|
| `/api/settings/github/start` | GET | `start_github_auth` | ⬜ Not Started |
| `/api/settings/github/callback` | GET | `complete_github_auth` | ⬜ Not Started |
| `/api/settings/github/unlink` | POST | `remove_github_auth` | ⬜ Not Started |

---

## Modals (in project.html)

| Modal | Purpose | Status |
|-------|---------|--------|
| Create File | New source file dialog | ⬜ Not Started |
| GitHub New Repo | Create new GitHub repo | ⬜ Not Started |
| GitHub Commit | Push commit dialog | ⬜ Not Started |
| GitHub Pull | Pull from GitHub | ⬜ Not Started |
| Phone Waiting | Waiting for phone | ⬜ Not Started |
| Phone Install | Installing app | ⬜ Not Started |
| Phone Screenshot | Taking screenshot | ⬜ Not Started |
| Fuzzy Prompt | Cmd-P search | ⬜ Not Started |
| Text Input | Generic text input | ⬜ Not Started |
| Warning Prompt | Confirmation dialog | ⬜ Not Started |
| Export Progress | Export in progress | ⬜ Not Started |
| Generic Progress | Generic progress | ⬜ Not Started |
| QEMU Sensor | Compass/accelerometer | ⬜ Not Started |
| What's New | Changelog modal | ⬜ Not Started |

---

## CSS Files to Copy

| File | Purpose | Status |
|------|---------|--------|
| `common/css/common.css` | Base styles | 🔄 Partial |
| `common/css/progress.css` | Progress bars | ⬜ Not Started |
| `common/fonts/fonts.css` | Font definitions | ⬜ Not Started |
| `ide/css/base.css` | IDE base | ⬜ Not Started |
| `ide/css/ide.css` | IDE layout | ⬜ Not Started |
| `ide/css/ib.css` | Interface Builder | ⬜ Not Started |
| `ide/css/project-list.css` | Project list | 🔄 Partial |
| `ide/css/codemirror-default.css` | Editor theme | ⬜ Not Started |

---

## JavaScript Files (to be ported to React)

| File | Purpose | Status |
|------|---------|--------|
| `ide/js/cloudpebble.js` | Main app initialization | ⬜ Not Started |
| `ide/js/sidebar.js` | Sidebar management | ⬜ Not Started |
| `ide/js/editor.js` | Code editor | ⬜ Not Started |
| `ide/js/compile.js` | Compilation UI | ⬜ Not Started |
| `ide/js/resources.js` | Resource management | ⬜ Not Started |
| `ide/js/settings.js` | Project settings | ⬜ Not Started |
| `ide/js/github.js` | GitHub integration | ⬜ Not Started |
| `ide/js/emulator.js` | Emulator UI | ⬜ Not Started |
| `ide/js/qemu.js` | QEMU control | ⬜ Not Started |
| `ide/js/ycm.js` | Autocomplete (YCMD) | ⬜ Not Started |
| `ide/js/autocomplete.js` | CodeMirror autocomplete | ⬜ Not Started |
| `ide/js/fuzzyprompt.js` | Cmd-P fuzzy finder | ⬜ Not Started |
| `ide/js/dependencies.js` | NPM dependencies | ⬜ Not Started |
| `ide/js/timeline.js` | Timeline preview | ⬜ Not Started |
| `ide/js/project_list.js` | Project list page | 🔄 Partial |
| `ide/js/ib/*.js` | Interface Builder | ⬜ Not Started |

---

## External Dependencies

| Library | Purpose | Status |
|---------|---------|--------|
| CodeMirror | Code editor | ⬜ Not Started |
| noVNC | Emulator display | ⬜ Not Started |
| jQuery | DOM manipulation | ⬜ Not Needed (React) |
| Backbone | MV* framework | ⬜ Not Needed (React) |
| Underscore | Utilities | ⬜ Not Needed (lodash/native) |
| Fuse.js | Fuzzy search | ⬜ Not Started |
| jsHint | JS linting | ⬜ Not Started |
| text-encoding | Text encoding | ⬜ Not Started |

---

## Current Progress

### ✅ Completed
1. Next.js app setup with TypeScript
2. Supabase integration (database)
3. Login API with Django PBKDF2 verification
4. Session management
5. Basic project list display

### 🔄 In Progress
1. Login page - needs HTML to match exactly
2. Project list page - needs HTML to match exactly
3. Create project modal - needs all fields

### ⬜ Next Steps (Priority Order)
1. **Copy exact HTML** from Django login.html → Next.js
2. **Copy exact HTML** from Django index.html (project list) → Next.js
3. **Copy common.css** completely
4. Verify HTML output matches Django using browser dev tools
5. Build project detail page (IDE)
6. Add CodeMirror editor
7. Implement file CRUD
8. Add build functionality
9. Add emulator (noVNC)

---

## Testing

- **Test User**: testuser / testpass123
- **Django Reference**: https://obelisk-sweet.exe.xyz
- **Vercel Deploy**: cloudpebble-peach.vercel.app

## Verification Method
1. Open Django version in browser
2. Open Next.js version in browser
3. Compare HTML output using browser DevTools
4. Must be **identical** structure and class names
