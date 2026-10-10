# Frontend (first release) — Design

Sub-project 7 of the GitKeepers build. Sub-projects 1 (auth + roles) and 2 (visits, AI
entry, follow-ups) are the backend this UI drives. Referrals, supplies, reports and sync
are later sub-projects; they appear in the UI only as "Coming soon".

## Goal

A browser PWA that barangay health workers, midwives and volunteers use on the laptop
that runs the local backend (phones/tablets on the same Wi-Fi also work). It covers
everything the backend already does: accounts, households and patients, DOH checkup forms
with AI suggest → review → confirm, visit timelines, follow-ups, plus a bento dashboard
with real counts. UI in English and Filipino.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Platform | Browser PWA on the same device, served by the local backend |
| Scope | Built features + dashboard; referrals/supplies/reports/sync as "Coming soon" |
| Language | English + Filipino toggle |
| Screen | Laptop first; layout collapses to one column at phone width |
| Visit flow | Form first, AI optional ("Fill from note" side panel) |
| Architecture | React + TypeScript + Vite SPA, built to `frontend/dist`, served by FastAPI on the API's port |

Rejected: a separately served frontend (two processes, two URLs, CORS) and a browser-side
IndexedDB copy of the data (duplicates sub-project 6 with no gain while browser and
backend share a machine).

## Architecture

- `gitkeepers/frontend/`: React 18, TypeScript, Vite, React Router, `vite-plugin-pwa`.
  No UI kit; plain CSS with design tokens. Tests: Vitest + Testing Library + jsdom.
- Production: `npm run build` → `frontend/dist`; the backend serves it at `/` on the same
  port as `/api/v1` (default `http://127.0.0.1:8765/`). One process, no CORS.
- Development: `npm run dev`; Vite proxies `/api` and `/health` to `http://127.0.0.1:8765`.
- Offline: all data lives in the backend's SQLite, which is already local. The service
  worker caches the app shell only (no API responses are cached).

### Visual style

Royal blue (primary), white (surfaces), gold (accents, AI highlights). Colors are CSS
custom properties on `:root`. Bento cards: rounded, white, soft shadow, grid that collapses
to one column under 640 px. Body text at least 16 px; tap targets at least 44 px. No
horizontal page scroll at 375 px.

## Screens and navigation

Shell: left sidebar (logo, nav) on laptop; top bar with a menu button at phone width.
Header right: EN/FIL toggle (remembered per browser), AI status chip ("AI ready" /
"AI off" from `/ai/status`), user menu (Profile, Sign out).

| Route | Screen |
|---|---|
| `/login`, `/signup` | Sign in / create account. After signup a pending volunteer sees "Waiting for admin approval" |
| `/` | Dashboard bento: follow-ups overdue / due / upcoming (each links to the filtered list), today's visits, drafts, household and patient totals, AI status, "New checkup" quick action. Referrals, Supplies, Reports cards greyed out "Coming soon" (not links) |
| `/households` | Search + paged list; "Register household" (with first members) |
| `/households/:id` | Household detail, members, "Add member" |
| `/patients` | Search + paged list |
| `/patients/:id` | Patient header, visit timeline (newest first, draft/final badges, form-type filter), the patient's follow-ups, "New checkup" (pick a form) |
| `/patients/:id/visits/new?form=` and `/visits/:id` | Checkup screen (below). Final visits open read-only with provenance badges |
| `/follow-ups` | Tabs Overdue / Due / Upcoming / Completed / Cancelled, name search; complete, reschedule, cancel per row |
| `/profile` | Edit name/email; change password |
| `/admin/users` | Admin only: pending accounts first; approve, disable, make admin, reset password |
| `/referrals`, `/supplies`, `/reports`, `/sync` | "Coming soon" placeholders, kept in the nav |

Guards: signed out → `/login` (the original path is restored after login). Non-admins do
not see the Admin nav item and the route shows "Not allowed". Any 401 clears the token and
returns to `/login`.

## Checkup screen and AI flow

Layout: form on the left (about two thirds), "Fill from note" panel on the right; at phone
width the panel is a collapsible section above the form.

The form renders from `GET /api/v1/forms/{type}`, so form JSON changes need no frontend
change. Inputs by field type:

| Type | Input |
|---|---|
| `integer`, `number` | Numeric input with the range as a hint |
| `boolean` | Three-state segmented control: Yes / No / not recorded |
| `choice` | Radio group |
| `choices` | Checkbox group |

Labels follow the language toggle. Required fields are marked. The form shows
"Draft — pending DOH review".

AI flow:

1. The worker types a note and presses "Fill from note". The panel shows a spinner and an
   elapsed-time counter ("about 30–70 s"). The form stays editable throughout.
2. When `POST /patients/{id}/suggestions` returns, each suggested value shows in a
   gold-outlined field with an "AI" tag and accept (✓) / reject (✕) buttons. A suggestion
   never overwrites a value the worker already entered; such a field shows
   "AI suggests: <value>" to accept or ignore. "Accept all" accepts every pending
   suggestion that would not overwrite. `problems` and `missing` are listed in the panel.
3. Accept → field source `ai_accepted`; editing an accepted value afterwards → the backend
   records `ai_edited`; reject → the suggestion is dropped. Save sends `values`,
   `suggestion_id` and `ai_accepted_fields` (fields accepted, whether or not later edited).
4. A 503 from suggestions, or AI status "off", shows "AI assistant unavailable — please
   fill in the form manually" in the panel; the form is unaffected.

Saving:

- "Save draft" at any time. "Finalize" requires the required fields and asks for
  confirmation ("Final visits can't be edited").
- Optional "Schedule follow-up" (date + reason). If the patient has an open follow-up, a
  checkbox "This visit completes the follow-up due <date>" sets `completes_follow_up_id`.
  The backend accepts both only when finalizing, so "Save draft" leaves them out of the
  request (the inputs keep their values for the later finalize).
- 422 `["<field>: <problem>", ...]` maps onto the matching fields' error text; lines that
  match no field show above the form. 409 shows "This visit was changed elsewhere —
  reload". Leaving with unsaved changes asks for confirmation.

## Frontend structure

```
frontend/
  index.html, vite.config.ts, tsconfig.json, package.json
  public/            icons, manifest assets
  src/
    main.tsx, App.tsx (routes)
    api/client.ts    fetch wrapper + one typed function per endpoint
    api/types.ts     types written from the OpenAPI schema
    auth/            token storage, AuthProvider/useAuth, RequireAuth/RequireAdmin
    i18n/            en.json, fil.json, I18nProvider/useT
    components/      BentoCard, FormField, ProvenanceBadge, Pager, SearchBox,
                     ConfirmDialog, Toast, Layout
    forms/           FormRenderer, suggestion reducer
    pages/           one file per screen
    styles/          tokens.css, base.css
```

- `api/client.ts`: adds `Authorization: Bearer <token>`, parses JSON, turns `{detail}`
  (string or list) into `ApiError(status, messages: string[])`, calls the global 401
  handler, and throws `NetworkError` when `fetch` itself fails.
- Token in `localStorage`, every access wrapped in try/catch (falls back to memory).
- Data loading: a small `useApi(fn, deps)` hook (loading / error / data / reload); no
  query library.
- `t(key)` falls back to English when a Filipino key is missing.

Errors in the UI: inline field errors for 422; a toast with `detail` for other API errors
(the backend guarantees it is safe to show); a full-page "Can't reach the GitKeepers
server on this laptop — is it running?" with Retry on `NetworkError`; 503 "Database busy"
toast with Retry.

## Backend additions

1. `GET /api/v1/dashboard` (signed in) →
   `{ follow_ups: {overdue, due, upcoming}, visits_today, drafts, households, patients,
   ai: {available, model} }`. Uses `core.clock.today()` and the same state rules as
   `/follow-ups`, so the counts equal the list totals.
2. `GET /api/v1/visits?date=&status=&limit=25&offset=0` (signed in): visits across
   patients, newest first, each with `patient_name`; limit capped at 100. Response uses the
   standard `{items, total, limit, offset}` page.
3. Static frontend: when `frontend/dist/index.html` exists, the backend serves its files at
   `/`, and any GET path not under `/api`, `/docs`, `/openapi.json`, `/redoc` or `/health`
   that matches no file returns `index.html`. Unknown `/api/...` paths keep the JSON 404.
   Without `dist`, behavior is unchanged. The `dist` location is read from config at call
   time (`FRONTEND_DIST`, overridable by env) so tests can point it at a temp folder.
4. README: frontend section (`npm install`, `npm run dev`, `npm run build`, `npm test`)
   and the new endpoints.

## Testing

Backend (`unittest`, existing `ApiTestCase` helpers):
- Dashboard counts equal `/follow-ups?state=` totals at a patched `today()`; drafts and
  today's visits counted; requires sign-in.
- Visits list: date and status filters, `patient_name`, limit capped at 100.
- Static serving with a temp `dist`: `/` and `/patients/5` return the index, assets are
  served, `/api/v1/unknown` returns the JSON 404; without `dist`, `/` is 404.

Frontend (Vitest, `fetch` stubbed at the client boundary):
- Client: bearer header, `{detail}` string/list mapping, 401 clears the token,
  network failure → `NetworkError`.
- Form renderer: each field type renders its input, three-state booleans, range hints,
  using the real `backend/forms/*.json` as fixtures.
- Suggestion reducer: accept, reject, accept-all; never overwrites a typed value;
  `ai_accepted_fields` in the save payload.
- Checkup page: 503 shows the manual fallback; 422 maps to fields; finalize confirms.
- i18n: toggle switches labels; missing key falls back to English; `fil.json` has every
  key in `en.json`.
- Guards: signed out → login; non-admin cannot open `/admin/users`.
- Dashboard renders counts; "Coming soon" cards are not links.

## Done criteria

- Backend suite green; `npm test` green; `npm run build` with zero TypeScript errors.
- Live smoke test: backend on a temp `APP_DATA_DIR`, built app opened at `:8765` in a
  browser: sign up as admin, register a household, record a checkup (AI if available,
  otherwise manual), see it on the dashboard.
- No horizontal scroll at 375 px.
- No git operations (the user handles git).

## Out of scope

Referrals, supplies, reports, sync screens (later sub-projects); voice dictation; push
notifications; caching API data in the browser; generated API clients.
