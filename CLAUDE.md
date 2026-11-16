# Daybook: notes for Claude

Daybook is a daily expense tracker for one person in India. It's used mainly as an iPhone Home Screen web app, hosted on GitHub Pages from this repository. The owner wants changes to be bug-free: **run the full test suite after every change** and look at the screenshots before calling something done.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | The entire app: CSS, markup and JavaScript in one file, no build step |
| `manifest.webmanifest` | Web app manifest (name, colours, icons, `display: standalone`) |
| `sw.js` | Service worker for offline launch: network-first for the page, cache-first for icons and fonts |
| `apple-touch-icon.png`, `icon-*.png` | Home Screen and browser icons (marigold square with two ink bars) |
| `tests/test_daybook.py` | 45 end-to-end Playwright tests |
| `README.md` | User-facing guide: hosting, installing on iPhone, backups |

Keep all app files at the top level. The owner uploads through GitHub's web page, and a flat folder keeps that easy.

## Run and test

The owner's Mac has no `python` command, and Homebrew's `python3` refuses a system-wide `pip install`. Use the virtual environment at `.venv` (git-ignored). If it's missing, create it once:

```
python3 -m venv .venv
.venv/bin/pip install "playwright>=1.45"
.venv/bin/python -m playwright install chromium
```

Then run the tests (the full suite takes about 2.5 minutes):

```
.venv/bin/python tests/test_daybook.py                      # everything
.venv/bin/python tests/test_daybook.py responsive_layouts   # one or more by name
```

The tests start their own local server, mark every guided tour as seen (pass `tours=True` to `Ctx` to see them), emulate iPhone screens in Chromium, and write screenshots to `tests/screenshots/` (git-ignored). Google Fonts are blocked during tests so layout checks are deterministic; `DAYBOOK_REAL_FONTS=1` loads them. To try the app by hand, run `python3 -m http.server` in the repo and open `http://localhost:8000`.

When you change something, add or update a test for it. Never weaken a test to make it pass without telling the owner why.

## How index.html is organised

The script is one IIFE, in this order: categories, helpers, validation, state, money formatting, data access, persistence, theme, navigation, shared row markup, the four views (Home, History, Insights, Plan), the add/edit sheet, welcome, the group and income sheets, guided tours, sample data, files (export/backup/restore), toast, event handlers, boot.

- All clicks go through one delegated listener keyed on `data-action` attributes.
- Each view re-renders with `innerHTML` (`renderHome`, `renderHistory`, `renderInsights`, `renderPlan`). `renderCurrent()` re-renders the visible view.
- Plan skips re-rendering while one of its inputs has focus (`planDirty`), so typing isn't interrupted.
- The bottom sheet (`#sheet`) is reused for add, edit, welcome, editing a group and editing a month's income. The `sh` variable holds its state; `sh.mode` is `add`, `edit`, `welcome`, `group` or `income`. Only `add` and `edit` use the keypad, `renderSheet` and `updateSheet`.
- "Groups" means two things in the code. `GROUPS` and a category's `group` are the fixed Needs / Wants / Debt / Future buckets. `S.settings.groups`, `groupOf()` and an expense's `g` are the owner's own expense groups (a car, a trip). In the UI, "group" always means the second kind; the CSV calls the first kind "Type".

## Data

**Expense:** `{id, a, c, n, d, p, t, g?, s?}` = id, amount, category id, note, date `YYYY-MM-DD` (local time), payment `upi|cash|card`, created timestamp, expense group id, and `s: 1` for sample data.

**Settings:** `{setup, currency, budget, income, incomes: {'YYYY-MM': amount}, alertAt (70|80|90), limits: {catId: amount}, groups: [group…], theme (auto|light|dark)}`. For savings and investment categories, the "limit" is a monthly goal.

**Group:** `{id, name, icon, target, apart, done}`. `target` is the planned total (0 = none), `apart: true` keeps the group out of the budget, `done: true` means finished. `icon` is one of `GROUP_ICONS`.

**Income:** `incomes` holds one amount per month. `income` is the single amount saved by versions before per-month income; `incomeFor()` uses it only while `incomes` is empty, and the first per-month edit (`setIncome()`) moves it to the earliest month with data and sets it to 0.

**Where it's stored**, decided by `HOSTED = !window.claude`:
- **GitHub Pages / hosted (`HOSTED` true):** `localStorage['daybook.v1'] = {v, mode, settings, months: {'YYYY-MM': [expense…]}}`, plus `localStorage['daybook.prefs']` for `lastCat`, `lastPay`, `lastBackup` and `tours` (which guided tours this device has seen). Data lives only on the device, and the iOS Home Screen app has storage separate from Safari. Backup/restore is the only way to move data.
- **claude.ai artifact:** the same file is also published as a Claude artifact, where `window.claude.use('db' | 'user' | 'downloads')` exists. Data lives in the private collection `data/users/<id>`, with docs `settings` and `m-YYYY-MM` (`{items: [...]}`). `localStorage` is only a cache there. This code path (the `Cloud` object, `firstCloud`, `applyDocs`, the write queue) is covered by the `cloud_*` tests through a mock in `MOCK_CLAUDE`. Don't remove it.

All loaded data goes through `cleanSettings` / `cleanMonths` / `cleanItem`, which drop invalid entries (including impossible dates like `2026-13-45`) and repair settings. Restore merges by id and never duplicates.

## Product rules (agreed with the owner)

**Categories,** with ids. Order matters for the UI.

| Group | Categories |
| --- | --- |
| Needs | `rent` Rent & Stay, `home` Home & Utilities, `groceries`, `bills` Recharge & Bills, `travel` Travel & Commute, `health` Health & Fitness |
| Wants | `food` Eating Out & Snacks, `fun` Entertainment, `subs` Subscriptions, `shopping` Shopping & Wants, `other` Gifts & Other |
| Debt | `card` Credit Card & EMI |
| Future (goals, not spending) | `invest` Investments, `savings` Savings |

**Fixed payments:** `rent`, `home`, `bills`, `subs` and `card` have `fixed: true`.

**Rules:**
- The monthly budget covers everything except the Future group. Savings and investments never count against it.
- Pace ("Today" marker on the Home tape) = fixed payments made + (budget − expected fixed) × day / days-in-month. Expected fixed is, per fixed category, the larger of its spend and its limit. This stops rent on the 1st from making the user look "ahead".
- "Safe to spend today" uses only everyday (non-fixed) spending.
- A category warns at `alertAt`% of its limit and is "over" above 100%. Fixed categories only warn when they go over, because paying rent in full is expected.
- While adding, the sheet shows a live hint. If the expense would go over a limit or the budget, the button turns red and reads "Add ₹X anyway". It never blocks saving.
- Insights: the daily chart, weekday chart and projection use everyday spending only. The projection adds expected fixed costs. The 50/30/20 check appears when that month has an income.
- **Income is per month.** A month without its own amount uses the latest earlier month's ("carried over from October"); nothing carries backward. Plan edits the current month (blank = use the carried amount, shown as the placeholder) and links to last month. Insights' "Change income" edits whichever month is shown.
- **Expense groups** are optional labels that span months, such as a car or a trip. Each expense keeps its category. A new expense starts with no group, except from a group's "Add to …" button, so everyday spending never lands in a group by accident.
- A group either counts in the budget (default) or is kept apart (`apart`). Apart expenses are left out of `stats()`: the budget, category limits, safe-to-spend, Insights charts and the 50/30/20 split. Insights says what it left out. History lists them and counts them in its totals, because it's a record of money spent.
- A group's planned amount works like a limit: the add sheet warns and shows "Add ₹X anyway" when an apart group would go over it, and the toast says when any group crosses it. Finished groups leave Home and the add screen but stay in History. Deleting a group keeps its expenses (with Undo).
- The welcome sheet can take amounts for categories the owner already knows (fixed payments first). They're saved as category limits.
- **Guided tours** (`TOURS`-style steps in `tourSteps()`): `guide` runs after the welcome (Start tracking or the sample month) and from Plan's "Take the tour"; `news` runs once for people who set up before groups and per-month income existed; `pick` is a one-time tip the first time the add sheet shows the group picker. A tour spotlights one element per step, can switch views, and returns to the starting view when it ends. Ending or skipping marks it seen in `daybook.prefs`. Keyboard shortcuts pause while a tour is open.
- History month and day totals count spending only, unless a Future category is the active filter.
- Default currency is INR with Indian digit grouping (`en-IN`). Compact amounts use K, L and Cr.

## Design and UI conventions

- Colours are CSS variables on `:root`, redefined for dark mode both under `prefers-color-scheme` and under `[data-theme="dark"]`. Use variables, never raw colours, for anything themed. `syncThemeColor()` keeps `<meta name="theme-color">` matched to `--bg`.
- Fonts: Bricolage Grotesque for display and numbers, Instrument Sans for text, with system fallbacks. Brand accent is marigold (`--brand`).
- Category colours and emoji icons live in `CATS`.
- Visible text uses typographic apostrophes and quotes (’ “ ”). Code uses straight quotes.
- Wrap `color-mix()` with a plain fallback declaration before it, for older iOS.
- **Class-name collisions bite:** `.empty` is the empty-state style. The amount display uses `.is-zero`. Grep for a class before adding one.
- Horizontal scrollers (`.quick`, `.fchips`) bleed to the screen edge using the `--gx` gutter variable (20px, 16px at 360px wide and below). Hard-coded margins caused a sideways wobble on small iPhones.

## iPhone specifics, don't regress

- Every input and select must be at least **16px**, or iOS zooms in on focus. There's a test for it.
- The add sheet's group picker sits beside the note field, with no height of its own, so the sheet is exactly as tall with or without groups. `layouts_with_groups` checks this.
- Safe areas: `viewport-fit=cover`; `:root` pads top and bottom with `env(safe-area-inset-*)`; `.app` and the tab bar pad left and right for landscape.
- The add sheet must fit without scrolling at Home Screen heights: 375×647 (SE), 393×798 (iPhone 15), 430×873 (Pro Max), and also 393×659 (Safari with bars).
  - This is handled by `max-height` breakpoints at 860, 760 and 600px, a landscape two-column layout (keypad beside the form, under 520px tall), and a desktop modal from 760px wide and 600px tall.
  - In portrait, `.sheet-grid`, `.sg-a` and `.sg-b` are `display: contents` so the sticky Save button sticks to the whole sheet.
- Opening the sheet resets its scroll position and hides any toast, so back-to-back entries work.
- Settings typed in Plan save on a 600ms debounce, and are flushed on `change`, `visibilitychange` (hidden) and `pagehide`, because iOS users swipe the app away quickly.
- The Home Screen meta tags and the manifest are in `<head>`. The service worker registers only when hosted, on https or localhost.

## Deploying

- **GitHub Pages:** serves this repo's `main` branch root. Usually only `index.html` changes. Commit and push (or the owner uploads it on github.com), and the app updates the next time it's opened online.
- **Icons or manifest changed:** bump `VERSION` in `sw.js`. The owner has to remove and re-add the Home Screen icon for iOS to show a new icon.
- **The claude.ai copy:** Claude Code can't update it. To update it, the owner attaches `index.html` in a claude.ai chat and asks to republish the Daybook artifact.

## Known limits

- Tests run in Chromium with iPhone emulation. Real Safari hasn't been tested automatically, so ask the owner to check new UI on the phone. Watch the keyboard over the note field, the native date picker, and the status bar in light and dark mode.
- Hosted data is per device, with no sync. Backups are the safety net. Plan shows the date of the last backup.
