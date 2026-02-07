# CloudPebble Next.js Development Workflow

## Development Process

1. **Local Development**: Use `npm run dev` until features work
2. **Build Test**: Run `npm run build` (or `vercel build`) to verify production build
3. **Deploy**: Only push to coredevices/cloudpebble after build succeeds

## Commands

```bash
# Local development
cd web-next
npm run dev

# Test production build  
npm run build

# Deploy (after build succeeds)
git add -A && git commit -m "message" && git push coredevices master
```

## Key Files

- `src/app/accounts/login/` - Login page
- `src/app/ide/` - Project list page
- `src/app/ide/project/[id]/` - IDE editor page
- `src/lib/auth.ts` - Authentication helpers
- `src/lib/supabase.ts` - Database client

## UI Matching

**CRITICAL**: UI must be IDENTICAL to Django version at https://obelisk-sweet.exe.xyz

- Copy HTML structure exactly from Django templates
- Copy CSS exactly from Django static files
- Use browser DevTools to compare rendered output
- Test every button and feature

## Test Credentials

- Username: `testuser`
- Password: `testpass123`
