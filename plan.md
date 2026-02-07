# CloudPebble Next.js Rewrite Plan

## Overview
Replace Django web frontend with Next.js on Vercel while keeping backend services on exe.dev.

## Architecture
```
┌─────────────┐      ┌──────────────────────┐
│   Browser   │─────▶│  Next.js on Vercel   │  (UI, API routes)
└──────┬──────┘      └──────────┬───────────┘
       │                        │
       │ WebSocket              │ Supabase
       │ (VNC, YCMD)            │ (PostgreSQL)
       ▼                        ▼
┌──────────────────────────────────────────┐
│           exe.dev services               │
│  nginx → QEMU, YCMD, Celery, S3          │
└──────────────────────────────────────────┘
```

## Database
- **Supabase**: https://hagijgvetkokhprpsnka.supabase.co
- Tables: cloudpebble_users, cloudpebble_sessions, cloudpebble_projects

## Backend Services (exe.dev)
- **S3**: `obelisk-sweet.exe.xyz:8003`
- **QEMU**: `wss://obelisk-sweet.exe.xyz/qemu/...`
- **YCMD**: `wss://obelisk-sweet.exe.xyz/ycmd/...`

## Deployments
- **Vercel Preview**: cloudpebble-qds98t4ei-core-devices.vercel.app
- **GitHub**: github.com/coredevices/cloudpebble (web-next folder)

## Phase 1: Core Infrastructure ✅
- [x] Create Next.js app in `/web-next/`
- [x] Set up Supabase client
- [x] Migration scripts in `/web-next/migrations/`
- [x] Deploy to Vercel

## Phase 2: Authentication ✅
- [x] Login page (UI matches Django original)
- [x] Django PBKDF2 password verification
- [x] Session management with cloudpebble_sessions table
- [x] Logout functionality

## Phase 3: Project List & Management 🔄 IN PROGRESS
- [x] Projects list page (`/ide/`) - UI updated
- [x] Create project modal
- [ ] UI pixel-perfect match with Django version
- [ ] Delete project
- [ ] Project settings

## Phase 4: IDE Core
- [ ] Project view page (`/ide/project/[id]`)
- [ ] Sidebar (files, resources)
- [ ] CodeMirror editor integration
- [ ] File CRUD (create, load, save, delete, rename)

## Phase 5: Resources
- [ ] Resource upload
- [ ] Resource display
- [ ] Resource identifiers

## Phase 6: Build System
- [ ] Trigger build (via Redis/Celery on exe.dev)
- [ ] Poll build status
- [ ] Display build log
- [ ] Download .pbw

## Phase 7: Emulator
- [ ] Launch emulator (POST to exe.dev)
- [ ] VNC display (noVNC, WebSocket to exe.dev)
- [ ] Button controls
- [ ] App install

## Phase 8: Code Completion (YCMD)
- [ ] Initialize YCMD session
- [ ] WebSocket connection to exe.dev
- [ ] Autocomplete integration with CodeMirror

## Phase 9: GitHub Integration (SHIMMED)
- [ ] UI elements present but non-functional
- [ ] Show "Coming soon" or similar

## Testing Credentials
- Username: testuser
- Password: testpass123

## Current Status
- Login page UI matches Django original ✅
- Project list page UI updated to match ✅
- Auth works with Supabase ✅
- Deployed to Vercel ✅

### Next Steps
1. Test full login flow in browser
2. Ensure pixel-perfect UI match
3. Build project detail page with editor
