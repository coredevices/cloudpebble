# CloudPebble Next.js Rewrite Plan

## Overview
Replace Django web frontend with Next.js on Vercel while keeping backend services on exe.dev.

## Architecture
```
┌─────────────┐      ┌──────────────────────┐
│   Browser   │─────▶│  Next.js on Vercel   │  (UI, API routes)
└──────┬──────┘      └──────────┬───────────┘
       │                        │
       │ WebSocket              │ HTTP
       │ (VNC, YCMD)            │ (PostgreSQL, Redis, S3)
       ▼                        ▼
┌──────────────────────────────────────────┐
│           exe.dev services               │
│  nginx → QEMU, YCMD, Celery, DB, S3      │
└──────────────────────────────────────────┘
```

## Backend Services (exe.dev)
- **PostgreSQL**: `obelisk-sweet.exe.xyz:5432` (user: postgres, db: postgres)
- **Redis**: `obelisk-sweet.exe.xyz:6379`
- **S3**: `obelisk-sweet.exe.xyz:8003`
- **QEMU**: `wss://obelisk-sweet.exe.xyz/qemu/...`
- **YCMD**: `wss://obelisk-sweet.exe.xyz/ycmd/...`

## Phase 1: Core Infrastructure
- [x] Expose PostgreSQL, Redis, S3 ports in docker-compose
- [x] Push docker-compose changes
- [x] Create Next.js app in `/web-next/`
- [x] Set up database connection (direct pg)
- [x] Set up S3 client (aws-sdk with custom endpoint)
- [x] Set up Redis client

## Phase 2: Authentication
- [x] Login page (replicate existing UI exactly)
- [x] Session management (use existing user: testuser/testpass123)
- [ ] Auth middleware for protected routes

## Phase 3: Project List & Management
- [x] Projects list page (`/ide/`)
- [x] Create project modal
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
- [ ] Trigger build (via Redis/Celery)
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

## Testing Checklist
- [ ] Login with testuser/testpass123
- [ ] View existing projects
- [ ] Open test project
- [ ] Edit source file
- [ ] Save file
- [ ] Build project
- [ ] View build log
- [ ] Run in emulator
- [ ] Install app to emulator
- [ ] Code completion works

## Current Status
**Phase 2: Authentication** - COMPLETE
**Phase 3: Project List** - IN PROGRESS

### Completed
- Next.js app created with TypeScript
- Database connection (pg)
- S3 client configured
- Redis client configured
- Login page with Django password verification
- Session management
- Project list page
- Create project modal

### Next Steps
- Deploy to Vercel and test database connectivity
- Test login with testuser/testpass123
- Build project detail page with editor
