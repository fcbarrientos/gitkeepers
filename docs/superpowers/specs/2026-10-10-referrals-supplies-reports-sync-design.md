# Referrals, Supplies, Reports and Sync — Design

Sub-projects 3–6 of GitKeepers, built together because they are small and share the same
patterns. They replace the four "Coming soon" tabs of the first frontend release.
Source requirements: FR-07, FR-09, FR-10, FR-11, FR-13 and AC-07, AC-09, AC-10, AC-11, AC-13.

## Decisions

| Question | Decision |
|---|---|
| Referral decision | Deterministic rules from JSON files marked "draft, pending professional review". AI is never used to flag |
| Referral slip | Print-friendly page; the browser's print dialog prints it or saves a PDF |
| Stock | Always the sum of recorded movements; no editable quantity |
| AI report draft | Local model sees aggregated numbers only; worker edits and approves; manual fallback |
| Sync | Manual transfer first: encrypted de-identified bundle file + authenticated RHU receipt. No online push yet (no RHU server exists) |
| Git | No git operations; the user commits |

## 3. Referrals

**Rules** live in `backend/referral_rules/<form_type>.json`:

```json
{
  "form_type": "prenatal",
  "verification": "draft, pending professional review",
  "rules": [
    {"id": "prenatal-high-bp", "when": {"any": [{"field": "bp_systolic", "op": ">=", "value": 140},
                                                 {"field": "bp_diastolic", "op": ">=", "value": 90}]},
     "urgency": "urgent", "reason": {"en": "High blood pressure in pregnancy", "fil": "Mataas na presyon habang buntis"}}
  ]
}
```

- Operators: `>=`, `<=`, `>`, `<`, `==` on a field's value; `is_true` for booleans; `any` / `all`
  groups. A missing (null) field never matches.
- Draft rule sets for all three forms:
  - Prenatal: BP ≥ 140/90; vaginal bleeding; temperature ≥ 38.0; severe headache with blurred vision.
  - Child growth: MUAC < 11.5; temperature ≥ 38.5.
  - BP follow-up: BP ≥ 180/110; chest pain; shortness of breath.
- Evaluated when a visit is **finalized**. Each matching rule creates a `referral_flags` row
  (visit, patient, rule id, reason, urgency) in the same transaction. Drafts are never flagged.
- `GET /api/v1/referral-rules` returns the rules, so the UI can show why a case was flagged.

**Referrals**:
- `POST /api/v1/referrals` `{flag_id?, patient_id, facility, reason, urgency, notes}` creates a
  referral (`issued`) after the worker reviews the pre-filled form. A referral can be made without
  a flag (manual referral). Making one from a flag marks the flag `referred`; a flag can also be
  `dismissed` with a note.
- `GET /api/v1/referrals?status=&patient_id=`, `GET /api/v1/referrals/{id}`.
- `GET /api/v1/referral-flags?status=open` lists open flags.
- Status `issued` → `sent` is set by Sync when its bundle is acknowledged.

**UI**: Referrals tab with "Open flags" and "Referrals" lists; flag → referral form (facility,
reason pre-filled, urgency, notes) → save → slip page `/referrals/:id/slip` (print layout with
patient, household location, visit values that triggered the rule, reason, facility, worker,
date). The checkup screen and patient page show a red flag banner when a visit has flags. The
dashboard gains an "Open referral flags" card.

## 4. Medicine and supplies

- Tables: `supply_items` (name, unit, low_stock_threshold, target_level, active) and
  `supply_movements` (item, kind `received` | `distributed` | `adjusted`, quantity, date, note,
  recorded_by). `adjusted` quantity may be negative; others must be positive. Distributing more
  than is in stock is rejected (422).
- `GET /api/v1/supplies` returns items with `on_hand` (sum of movements) and `low` flag;
  `POST /api/v1/supplies`, `PATCH /api/v1/supplies/{id}`;
  `GET|POST /api/v1/supplies/{id}/movements`;
  `GET /api/v1/supplies/request-list` → low items with `request_quantity = target_level - on_hand`.
- UI: inventory cards (on hand, unit, low badge), item detail with movement history and a
  "Record received / distributed / adjustment" form, request list page with print and CSV export.
- Dashboard "Low-stock supplies" card becomes live.

## 5. Reports and AI drafts

- `GET /api/v1/reports/summary?period=week|month&date=YYYY-MM-DD` returns, for the period
  containing `date` and for the previous period:
  - visits by form and status, new households, new patients;
  - follow-ups completed, overdue at period end;
  - referral flags raised, referrals issued, grouped by reason;
  - supplies received and distributed per item, items low at period end;
  - `unsynced_records`: count of records not yet acknowledged by the RHU.
- UI: period picker, report cards with current vs previous values, a summary table, CSV export,
  and a notice when `unsynced_records > 0` ("N records not yet transferred to the RHU").
- **AI draft** `POST /api/v1/reports/drafts {period, date}`: builds a prompt from the summary
  numbers only (no names, no notes, no IDs), asks the local model for a short draft of possible
  community health program and service needs, and returns `{draft_id, text, figures}`. 503 when
  the model is unavailable (worker writes the text by hand).
- `PATCH /api/v1/reports/drafts/{id} {text, status: approved}` saves the edited, approved text;
  approved drafts are read-only. `GET /api/v1/reports/drafts?period=&date=` lists them.
- The prompt states the AI must not make clinical or resource-allocation decisions; the UI
  labels the text "Draft for professional review".

## 6. Sync (manual transfer)

- Record types synced: households, patients, visits, follow-ups, referrals, supply movements.
- **State** is derived, not stored per record: tables `sync_bundles` (id, created_at,
  record_count, acknowledged_at, created_by) and `sync_bundle_records` (bundle_id, record_type,
  record_id, record_updated_at). A record is
  - `synced` if an acknowledged bundle holds it with its current `updated_at`;
  - `awaiting` if an unacknowledged bundle holds it with its current `updated_at`;
  - `pending` otherwise (new, or edited after export).
  Known limit: `updated_at` has one-second precision.
- `GET /api/v1/sync/status` → pending/awaiting/synced counts per type, last acknowledged bundle,
  open bundles, whether a passphrase is set.
- `PUT /api/v1/sync/settings {passphrase}` (admin, at least 12 characters) and a generated
  `station_id`, stored in a `settings` table.
- `POST /api/v1/sync/bundles` (admin) packs all pending records with `core.sync.create_sync_bundle`
  (de-identified payload + encrypted identity envelope), records the bundle, and returns the
  bundle JSON as a file download `gitkeepers-<station>-<bundle id>.json`. 409 when nothing is
  pending; 422 when no passphrase is set.
- `POST /api/v1/sync/receipts` (admin) accepts an RHU receipt
  `{format: "gitkeepers-receipt-v1", bundle_id, record_count, signature}` where `signature` is
  HMAC-SHA256 over `bundle_id:record_count` with a key derived from the passphrase. Valid →
  bundle acknowledged, its referrals become `sent`. Wrong signature, unknown bundle or count
  mismatch → 422 with a clear message; nothing changes.
- `backend/scripts/rhu_receipt.py BUNDLE_FILE` (RHU side) checks a bundle and writes its receipt,
  so the flow can be completed and tested end to end.
- UI: Sync tab with status cards, pending counts, "Create transfer file", list of bundles
  awaiting receipt (re-download), "Import RHU receipt" file picker with success/error messages,
  and (admin) passphrase setting. Header shows a small "N not synced" chip; the dashboard
  "Sync status" card becomes live.

## Errors and testing

- All new endpoints follow the existing patterns: `{detail}` errors, 422 lists of
  `"<field>: <problem>"`, signed-in by default, admin where stated.
- Backend tests per module (rules engine, flags on finalize, referrals, supplies and stock
  rules, report aggregation against known fixtures, AI draft with a fake model and the 503 path,
  sync state transitions, bundle contents de-identified, receipt signature/mismatch handling).
- Frontend tests per tab: flag → referral → slip; record movement → stock and low badge;
  request list; report period switch and unsynced notice; AI draft edit/approve and 503
  fallback; create bundle, import good and bad receipts.
- Done: backend suite green, `npm test` green, `npm run build` clean, live smoke on a temp
  data dir covering one full referral, supply and sync round trip.

## Out of scope

Online push sync to an RHU server, conflict merging beyond re-export, multi-device sync between
health workers, DOH official form layouts (rules and slips stay "pending review").
