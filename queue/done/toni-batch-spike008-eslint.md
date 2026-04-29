# SPIKE-008 ESLint Enforcement Batch
# Batch: toni-batch-spike008-eslint
# Product: Yorsie
# Briefs: 1
# depends_on_batches: toni-batch-spike008-polish-01
# Rule: Verify with build + lint after all briefs complete. Do NOT run Playwright E2E tests during batch execution.
## Design system: yorsie-design-system-D154-v1.md
## This batch must not increase total Supabase queries on page load (D-170).

---

## Brief Y-SPIKE008-ESLINT-001: ESLint no-restricted-syntax rule for raw HTML elements

### Decision anchor
D-198: UI unification before family launch. SPIKE-008 unified component system.

### Context
SPIKE-008 built 19 unified components in `src/components/ui/` and migrated Food + Supplements. Without ESLint enforcement, future briefs (including Toni) can bypass the library by writing raw JSX elements, creating visual inconsistency and undoing the migration.

### Requirements

1. **Add ESLint rule to `.eslintrc.cjs` (or `.eslintrc.json`, whichever exists):**

Add `no-restricted-syntax` rule targeting raw HTML form elements in JSX. The rule should error (not warn) when any of these raw elements appear in files under `src/` EXCEPT files inside `src/components/ui/`:

- `<input` → Use `TextInput`, `NumberInput`, `SearchInput`, or `Checkbox` from `@/components/ui`
- `<button` → Use `Button` from `@/components/ui`
- `<select` → Use `Select` from `@/components/ui`
- `<textarea` → Use `TextArea` from `@/components/ui`

2. **Use ESLint override to exempt `src/components/ui/` directory.** The library components themselves must use raw elements — only consumer code is restricted.

3. **Fix any existing violations.** Run the lint after adding the rule. If any files outside `src/components/ui/` use raw elements, replace them with the unified component equivalents. Import from `@/components/ui` barrel export (`import { Button, TextInput, ... } from '@/components/ui'`).

4. **Do NOT change any component behavior.** This is a lint rule + violation fixes only. No new props, no styling changes, no layout changes.

### ASCII Layout
N/A — this is a tooling brief, not a UI brief.

### Acceptance criteria
- [ ] ESLint rule added and configured
- [ ] `src/components/ui/` exempted via override
- [ ] `npm run lint` passes with zero errors
- [ ] `npm run build` passes
- [ ] No raw `<input>`, `<button>`, `<select>`, `<textarea>` in any file outside `src/components/ui/`
- [ ] All replacements use barrel import from `@/components/ui`

### Expected output file
`.eslintrc.cjs` (or equivalent) + any fixed source files

### Estimated tokens
~3,000-5,000
