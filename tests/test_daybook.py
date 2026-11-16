"""End-to-end tests for Daybook (index.html).

Setup, once:
    pip install "playwright>=1.45"
    python -m playwright install chromium

Run all tests, or name some:
    python tests/test_daybook.py
    python tests/test_daybook.py add_expense_with_keypad responsive_layouts

Screenshots from the layout test go to tests/screenshots/.
Set DAYBOOK_CHROME to a Chromium binary to use a specific browser.
Remote fonts are blocked so results don't depend on the network; set
DAYBOOK_REAL_FONTS=1 to load Google Fonts as real users get them.
"""
import json, threading, functools, http.server, socketserver, datetime, calendar, traceback, sys, os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = str(Path(__file__).resolve().parent.parent)
SHOTS = str(Path(__file__).resolve().parent / 'screenshots')
os.makedirs(SHOTS, exist_ok=True)
CHROME = os.environ.get('DAYBOOK_CHROME') or None
REAL_FONTS = os.environ.get('DAYBOOK_REAL_FONTS') == '1'
IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=ROOT))
PORT = httpd.server_address[1]
URL = f'http://localhost:{PORT}/index.html'
threading.Thread(target=httpd.serve_forever, daemon=True).start()

# A stand-in for the claude.ai runtime (window.claude): db, user and downloads.
MOCK_CLAUDE = r"""
(() => {
  const KEY='__mockdb';
  const store = JSON.parse(localStorage.getItem(KEY) || '{}');
  const persist = () => localStorage.setItem(KEY, JSON.stringify(store));
  const freeze = o => { if (o && typeof o === 'object') { Object.values(o).forEach(freeze); Object.freeze(o); } return o; };
  const listeners = [];
  const snap = prefix => {
    const docs = Object.keys(store).filter(p => p.startsWith(prefix + '/') && !p.slice(prefix.length + 1).includes('/'))
      .map(p => ({id: p.slice(prefix.length + 1), exists: true, data: () => freeze(JSON.parse(JSON.stringify(store[p]))), metadata: {fromCache:false, hasPendingWrites:false}}));
    return {docs, size: docs.length, empty: !docs.length, metadata: {fromCache:false, hasPendingWrites:false}, docChanges: () => []};
  };
  const notify = () => listeners.forEach(l => setTimeout(() => l.next(snap(l.prefix)), 5));
  window.__writes = [];
  const db = {collection(path){ return {path, doc(id){ const p = path + '/' + id; return {id, path: p,
      async set(d){ if (typeof d !== 'object' || Array.isArray(d)) throw {code:'invalid_argument'}; window.__writes.push(['set', id]); store[p] = JSON.parse(JSON.stringify(d)); persist(); notify(); },
      async delete(){ window.__writes.push(['delete', id]); delete store[p]; persist(); notify(); },
      async get(){ return {id, exists: p in store, data: () => store[p]}; }}; },
    onSnapshot(next, err){ const l = {prefix: path, next, err}; listeners.push(l); setTimeout(() => next(snap(path)), 40); return () => {}; }}; }};
  const user = {async id(){ return 'u_test'; }, async isOwner(){ return true; }};
  window.__downloads = [];
  const downloads = {async save({filename, data}){ window.__downloads.push({filename, size: String(data).length, head: String(data).slice(0, 60)}); return {status:'saved'}; }};
  window.claude = {use(name){ return new Promise(r => setTimeout(() => r(name === 'db' ? db : name === 'user' ? user : name === 'downloads' ? downloads : null), 25)); }};
})();
"""

results = []
def test(fn):
    results.append(fn)
    return fn

class Ctx:
    def __init__(self, browser, mobile=True, viewport=(390, 844), claude=False, seed=None, clock=None, sw=False):
        opts = dict(viewport={'width': viewport[0], 'height': viewport[1]}, service_workers='allow' if sw else 'block', accept_downloads=True)
        if mobile:
            opts.update(device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=IPHONE_UA)
        self.ctx = browser.new_context(**opts)
        if not REAL_FONTS:
            self.ctx.route('**/fonts.googleapis.com/**', lambda r: r.abort())
            self.ctx.route('**/fonts.gstatic.com/**', lambda r: r.abort())
        if seed is not None:
            self.ctx.add_init_script("if (!sessionStorage.getItem('__seeded')) { sessionStorage.setItem('__seeded','1'); " +
                                     "".join(f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});" for k, v in seed.items()) + "}")
        if claude:
            self.ctx.add_init_script(MOCK_CLAUDE)
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append('pageerror: ' + str(e)))
        self.page.on('console', lambda m: self.errors.append('console: ' + m.text + ' @ ' + str(m.location.get('url')))
                     if m.type == 'error' and 'ERR_NAME_NOT_RESOLVED' not in m.text and 'fonts.g' not in str(m.location.get('url', '')) else None)
        if clock:
            self.page.clock.set_fixed_time(clock)
        self.mobile = mobile
    def go(self, wait=500):
        self.page.goto(URL); self.page.wait_for_timeout(wait); return self.page
    def tap(self, sel):
        if self.mobile: self.page.tap(sel)
        else: self.page.click(sel)
        self.page.wait_for_timeout(60)
    def close(self):
        errs = list(self.errors); self.ctx.close(); return errs

def setup(c, budget='30000'):
    p = c.page
    p.wait_for_selector('#wBudget', state='visible')
    p.fill('#wBudget', budget)
    c.tap('[data-action="welcome-start"]')
    p.wait_for_timeout(400)

def sample(c):
    c.page.wait_for_selector('[data-action="welcome-sample"]', state='visible')
    c.tap('[data-action="welcome-sample"]'); c.page.wait_for_timeout(450)

def add(c, amount, cat=None, note=None, when=None, pay=None):
    p = c.page
    c.tap('.fab'); p.wait_for_selector('#saveBtn', state='visible'); p.wait_for_timeout(350)
    for k in str(amount): c.tap(f'.key[data-k="{k}"]')
    if cat: c.tap(f'.cp[data-cat="{cat}"]')
    if note: p.fill('#noteIn', note)
    if when: c.tap(f'[data-action="pick-date"]:has-text("{when}")')
    if pay: c.tap(f'[data-action="pick-pay"][data-v="{pay}"]')
    c.tap('#saveBtn'); p.wait_for_timeout(400)

def store(p):
    return p.evaluate("JSON.parse(localStorage.getItem('daybook.v1') || 'null')")

def items(p):
    s = store(p) or {'months': {}}
    return [e for k in s['months'] for e in s['months'][k]]

def text(p, sel):
    return p.inner_text(sel)

def toast(p):
    return p.inner_text('#toastText')

def check(cond, msg):
    if not cond: raise AssertionError(msg)

# ------------------------------------------------------------------ core flows
@test
def welcome_and_first_budget(b):
    c = Ctx(b); p = c.go()
    check(p.is_visible('.welcome'), 'welcome sheet should show on first launch')
    setup(c, '30000')
    check(p.is_hidden('#sheet'), 'sheet closes after Start tracking')
    check('30,000' in text(p, '.hero-sub'), 'hero shows budget: ' + text(p, '.hero-sub'))
    s = store(p); check(s['settings']['budget'] == 30000 and s['settings']['setup'], 'budget saved')
    p.reload(); p.wait_for_timeout(500)
    check(p.is_hidden('#sheet'), 'no welcome after setup on reload')
    return c.close()

@test
def welcome_escape_counts_as_done(b):
    c = Ctx(b, mobile=False); p = c.go()
    p.keyboard.press('Escape'); p.wait_for_timeout(400)
    p.reload(); p.wait_for_timeout(500)
    check(p.is_hidden('#sheet'), 'welcome should not come back after dismissing')
    return c.close()

@test
def add_expense_with_keypad(b):
    c = Ctx(b); p = c.go(); setup(c)
    add(c, 250, 'groceries', 'Veggies')
    check('Added ₹250 to Groceries' in toast(p), 'toast: ' + toast(p))
    check(text(p, '.list .row-title') == 'Veggies', 'recent shows the expense')
    check('₹29,750' in text(p, '.hero-num'), 'hero updates: ' + text(p, '.hero-num'))
    check('₹250' in text(p, '.trio'), 'spent today updates')
    it = items(p); check(len(it) == 1 and it[0]['a'] == 250 and it[0]['c'] == 'groceries' and it[0]['p'] == 'upi', 'stored item ' + str(it))
    return c.close()

@test
def keypad_edge_cases(b):
    c = Ctx(b); p = c.go(); setup(c)
    c.tap('.fab'); p.wait_for_selector('#saveBtn', state='visible'); p.wait_for_timeout(350)
    check(p.is_disabled('#saveBtn'), 'save disabled at zero')
    c.tap('.key[data-k="."]'); check(text(p, '#amtVal') == '0.', 'decimal first gives 0.')
    for k in '555': c.tap(f'.key[data-k="{k}"]')
    check(text(p, '#amtVal') == '0.55', 'max two decimals: ' + text(p, '#amtVal'))
    for _ in range(5): c.tap('.key[data-k="del"]')
    check(text(p, '#amtVal') == '0' and 'is-zero' in p.get_attribute('#amtBox', 'class'), 'cleared shows 0')
    for k in '007': c.tap(f'.key[data-k="{k}"]')
    check(text(p, '#amtVal') == '7', 'leading zeros dropped: ' + text(p, '#amtVal'))
    c.tap('.key[data-k="del"]')
    for k in '123456789': c.tap(f'.key[data-k="{k}"]')
    check(text(p, '#amtVal') == '1,23,45,678', 'eight digit cap with Indian grouping: ' + text(p, '#amtVal'))
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    check(p.is_hidden('#sheet') and items(p) == [], 'closing does not save')
    return c.close()

@test
def undo_add(b):
    c = Ctx(b); p = c.go(); setup(c)
    add(c, 99, 'food', 'Snack')
    c.tap('#toastBtn'); p.wait_for_timeout(300)
    check(items(p) == [], 'undo removes the expense')
    check('No expenses yet' in text(p, '#view-home'), 'empty state back')
    return c.close()

@test
def edit_expense(b):
    c = Ctx(b, clock=datetime.datetime(2026, 10, 15, 12, 0)); p = c.go(); setup(c)
    add(c, 100, 'food', 'Lunch')
    c.tap('.list .row'); p.wait_for_selector('#saveBtn', state='visible'); p.wait_for_timeout(350)
    check(text(p, '#amtVal') == '100' and p.get_attribute('.cp[data-cat="food"]', 'aria-checked') == 'true', 'edit sheet prefilled')
    for _ in range(3): c.tap('.key[data-k="del"]')
    for k in '300': c.tap(f'.key[data-k="{k}"]')
    c.tap('.cp[data-cat="fun"]'); c.tap('[data-action="pick-date"]:has-text("Yesterday")'); c.tap('[data-action="pick-pay"][data-v="cash"]')
    check(text(p, '#saveBtn').startswith('Save'), 'edit button label')
    c.tap('#saveBtn'); p.wait_for_timeout(400)
    it = items(p); check(len(it) == 1 and it[0]['a'] == 300 and it[0]['c'] == 'fun' and it[0]['d'] == '2026-10-14' and it[0]['p'] == 'cash', 'edited item ' + str(it))
    check(toast(p) == 'Changes saved', 'toast after edit')
    return c.close()

@test
def edit_moves_expense_across_months(b):
    c = Ctx(b, clock=datetime.datetime(2026, 11, 1, 9, 0)); p = c.go(); setup(c)
    add(c, 40, 'travel', 'Metro')
    c.tap('.list .row'); p.wait_for_timeout(400)
    c.tap('[data-action="pick-date"]:has-text("Yesterday")'); c.tap('#saveBtn'); p.wait_for_timeout(400)
    s = store(p)
    check(list(s['months'].keys()) == ['2026-10'] and s['months']['2026-10'][0]['d'] == '2026-10-31', 'moved to October: ' + str(s['months']))
    check('₹30,000' in text(p, '.hero-num'), 'November total no longer includes it')
    return c.close()

@test
def delete_and_undo(b):
    c = Ctx(b); p = c.go(); setup(c)
    add(c, 500, 'shopping', 'Shirt')
    c.tap('.list .row'); p.wait_for_timeout(400)
    c.tap('[data-action="sheet-delete"]'); p.wait_for_timeout(400)
    check(items(p) == [] and 'Deleted ₹500' in toast(p), 'deleted')
    c.tap('#toastBtn'); p.wait_for_timeout(300)
    check(len(items(p)) == 1, 'undo delete restores')
    return c.close()

@test
def limits_warnings_and_over_budget(b):
    c = Ctx(b); p = c.go(); setup(c, '10000')
    c.tap('.tab[data-view="plan"]')
    p.fill('input[data-limit="food"]', '500'); p.dispatch_event('input[data-limit="food"]', 'change')
    check(store(p)['settings']['limits'].get('food') == 500, 'limit saved')
    c.tap('.tab[data-view="home"]')
    c.tap('.fab'); p.wait_for_timeout(350)
    for k in '450': c.tap(f'.key[data-k="{k}"]')
    c.tap('.cp[data-cat="food"]')
    check('warn' in p.get_attribute('#sheetHint', 'class') and '90%' in text(p, '#sheetHint'), 'warn hint: ' + text(p, '#sheetHint'))
    c.tap('#saveBtn'); p.wait_for_timeout(400)
    check('90% of its limit' in toast(p), 'warn toast: ' + toast(p))
    check('used 90%' in text(p, '.alerts'), 'home alert shows')
    c.tap('.fab'); p.wait_for_timeout(350)
    for k in '100': c.tap(f'.key[data-k="{k}"]')
    c.tap('.cp[data-cat="food"]')
    check('over' in p.get_attribute('#sheetHint', 'class') and 'anyway' in text(p, '#saveBtn'), 'over hint + Add anyway: ' + text(p, '#saveBtn'))
    c.tap('#saveBtn'); p.wait_for_timeout(400)
    check('₹50 over' in text(p, '.alerts'), 'over alert: ' + text(p, '.alerts'))
    add(c, 9600, 'shopping')
    check('is-over' in p.get_attribute('.hero', 'class') and 'over budget' in text(p, '.hero-num'), 'hero over budget')
    check('over your monthly budget' in toast(p), 'budget crossing toast: ' + toast(p))
    c.tap('.alert'); p.wait_for_timeout(300)
    check(p.is_visible('#view-history') and p.get_attribute('#histChips [data-cat="food"]', 'aria-pressed') == 'true', 'alert opens filtered history')
    return c.close()

@test
def fixed_payments_do_not_nag(b):
    c = Ctx(b); p = c.go(); setup(c, '30000')
    c.tap('.tab[data-view="plan"]'); p.fill('input[data-limit="rent"]', '12000'); p.dispatch_event('input[data-limit="rent"]', 'change')
    c.tap('.tab[data-view="home"]')
    add(c, 12000, 'rent', 'Rent')
    check(not p.query_selector('.alerts'), 'paying rent in full is not a warning')
    check(not p.query_selector('.cat-row.warn'), 'rent row not in warning colour')
    return c.close()

@test
def savings_goal_hint(b):
    c = Ctx(b); p = c.go(); setup(c)
    c.tap('.tab[data-view="plan"]'); p.fill('input[data-limit="savings"]', '3000'); p.dispatch_event('input[data-limit="savings"]', 'change')
    c.tap('.tab[data-view="home"]'); c.tap('.fab'); p.wait_for_timeout(350)
    for k in '3000': c.tap(f'.key[data-k="{k}"]')
    c.tap('.cp[data-cat="savings"]')
    check('good' in p.get_attribute('#sheetHint', 'class'), 'goal reached hint is positive: ' + text(p, '#sheetHint'))
    c.tap('#saveBtn'); p.wait_for_timeout(400)
    check('₹30,000' in text(p, '.hero-num'), 'savings do not reduce spending budget')
    check('₹3,000' in text(p, '.trio'), 'saved & invested shows')
    return c.close()

@test
def category_row_opens_prefilled_sheet(b):
    c = Ctx(b); p = c.go(); sample(c)
    c.tap('.cat-row[data-cat="groceries"]'); p.wait_for_timeout(400)
    check(p.get_attribute('.cp[data-cat="groceries"]', 'aria-checked') == 'true', 'groceries preselected')
    return c.close()

@test
def history_search_filter_and_paging(b):
    c = Ctx(b); p = c.go(); sample(c)
    c.tap('.tab[data-view="history"]')
    n_all = len(p.query_selector_all('#histList .row'))
    check(n_all == 120, f'first page has 120 rows, got {n_all}')
    c.tap('[data-action="hist-more"]')
    check(len(p.query_selector_all('#histList .row')) > 120, 'show older loads more')
    p.fill('#histSearch', 'metro')
    titles = [t.inner_text() for t in p.query_selector_all('#histList .row-title')]
    check(titles and all('metro' in t.lower() for t in titles), 'search filters')
    check('expense' in text(p, '#histSum'), 'search summary shown')
    p.fill('#histSearch', 'zzzz-nothing')
    check('No expenses match' in text(p, '#histList'), 'no-match message')
    p.fill('#histSearch', '')
    c.tap('#histChips [data-cat="groceries"]')
    subs = [t.inner_text() for t in p.query_selector_all('#histList .row-sub')]
    check(subs and all(s.startswith('Groceries') for s in subs), 'category filter')
    return c.close()

@test
def insights_navigation_and_charts(b):
    c = Ctx(b, clock=datetime.datetime(2026, 10, 27, 20, 0)); p = c.go(); sample(c)
    c.tap('.tab[data-view="insights"]')
    check('October 2026' in text(p, '.ins-head'), 'current month title')
    check(p.is_disabled('[data-action="ins-next"]'), 'next disabled on current month')
    check(len(p.query_selector_all('.dbar')) == 31 and len(p.query_selector_all('.dbar.fut')) == 4, 'day bars incl. future days')
    c.tap('.dbar[data-d="3"]')
    check(text(p, '#dayCap').startswith('Oct 3:'), 'bar caption: ' + text(p, '#dayCap'))
    for sec in ['Where it went', 'Everyday spending', 'Needs, wants', 'Month by month', 'Costliest days', 'How you paid', 'Biggest expenses']:
        check(sec in text(p, '#view-insights'), 'section present: ' + sec)
    c.tap('[data-action="ins-prev"]')
    check('September 2026' in text(p, '.ins-head') and not p.is_disabled('[data-action="ins-next"]'), 'previous month')
    check('Against budget' in text(p, '.kpis'), 'past month KPI')
    c.tap('[data-action="ins-prev"]'); c.tap('[data-action="ins-prev"]')
    check('Nothing logged in July' in text(p, '#view-insights'), 'empty month message')
    return c.close()

@test
def plan_saves_even_on_quick_close(b):
    c = Ctx(b); p = c.go(); setup(c)
    c.tap('.tab[data-view="plan"]')
    p.fill('#budgetIn', '45,000')
    p.reload(); p.wait_for_timeout(500)
    check(store(p)['settings']['budget'] == 45000, 'budget flushed on page hide: ' + str(store(p)['settings']['budget']))
    c.tap('.tab[data-view="plan"]')
    check(p.input_value('#budgetIn') == '45,000', 'shown with grouping')
    return c.close()

@test
def theme_and_currency(b):
    c = Ctx(b); p = c.go(); setup(c)
    c.tap('.tab[data-view="plan"]')
    c.tap('[data-action="theme"][data-v="dark"]')
    check(p.get_attribute('html', 'data-theme') == 'dark', 'dark theme applied')
    check(p.get_attribute('meta[name="theme-color"]', 'content').upper() == '#11131B', 'status bar colour follows theme')
    p.select_option('#curSel', 'USD'); p.wait_for_timeout(200)
    c.tap('.tab[data-view="home"]')
    check('$30,000' in text(p, '.hero-num'), 'currency switched: ' + text(p, '.hero-num'))
    p.reload(); p.wait_for_timeout(500)
    check(p.get_attribute('html', 'data-theme') == 'dark' and '$' in text(p, '.hero-num'), 'theme and currency persist')
    return c.close()

@test
def fill_limits_from_last_month(b):
    c = Ctx(b); p = c.go(); sample(c)
    c.tap('.tab[data-view="plan"]')
    c.tap('[data-action="fill-last"]')
    lim = store(p)['settings']['limits']
    check(all(v % 100 == 0 for v in lim.values()) and lim.get('rent') == 12000, 'limits rounded from last month ' + str(lim))
    return c.close()

@test
def sample_remove_and_erase(b):
    c = Ctx(b); p = c.go(); sample(c)
    check(len(items(p)) > 100, 'sample loaded')
    add(c, 77, 'food', 'Mine')
    c.tap('.tab[data-view="plan"]'); c.tap('[data-action="sample-remove"]'); p.wait_for_timeout(300)
    it = items(p); check(len(it) == 1 and it[0]['n'] == 'Mine', 'only real data remains')
    c.tap('[data-action="erase"]')
    check('Tap again' in text(p, '[data-action="erase"]'), 'erase asks twice')
    c.tap('[data-action="erase"]'); p.wait_for_timeout(500)
    check(p.is_visible('.welcome') and items(p) == [], 'erased and welcome shown')
    return c.close()

@test
def backup_and_restore(b):
    c = Ctx(b, mobile=False); p = c.go(); sample(c)
    n = len(items(p))
    c.tap('.tab[data-view="plan"]')
    with p.expect_download() as d:
        c.tap('[data-action="backup"]')
    path = d.value.path(); data = json.load(open(path))
    check(data['app'] == 'daybook' and sum(len(v) for v in data['months'].values()) == n, 'backup contains everything')
    check(d.value.suggested_filename.startswith('daybook-backup-'), 'backup filename')
    p.wait_for_timeout(300)
    check('Last backup: Today' in text(p, '#view-plan'), 'last backup noted')
    c.tap('[data-action="erase"]'); c.tap('[data-action="erase"]'); p.wait_for_timeout(500)
    p.set_input_files('#restoreIn', path); p.wait_for_timeout(500)
    check(f'Restored {n} expenses' in toast(p), 'restore toast: ' + toast(p))
    check(len(items(p)) == n and store(p)['settings']['budget'] == 44000, 'everything restored')
    check(p.is_hidden('#sheet'), 'welcome closed after restore')
    p.set_input_files('#restoreIn', path); p.wait_for_timeout(400)
    check('already here' in toast(p) and len(items(p)) == n, 'second restore adds no duplicates')
    bad = os.path.join(SHOTS, '_not_a_backup.json'); open(bad, 'w').write('{"hello": 1}')
    p.set_input_files('#restoreIn', bad); p.wait_for_timeout(400)
    check('isn’t a Daybook backup' in toast(p), 'rejects other files')
    return c.close()

@test
def csv_export(b):
    c = Ctx(b, mobile=False); p = c.go(); setup(c)
    add(c, 120, 'food', 'Dosa, "masala"')
    c.tap('.tab[data-view="plan"]')
    with p.expect_download() as d:
        c.tap('[data-action="export"]')
    raw = open(d.value.path(), encoding='utf-8-sig').read().splitlines()
    check(raw[0] == 'Date,Category,Group,Note,Amount,Currency,Paid with', 'csv header')
    check(raw[1].endswith(',Eating Out & Snacks,Wants,"Dosa, ""masala""",120,INR,UPI'), 'csv row escaping: ' + raw[1])
    return c.close()

@test
def back_to_back_entries(b):
    c = Ctx(b); p = c.go(); setup(c)
    add(c, 30, 'food', 'Tea')
    c.tap('.fab'); p.wait_for_timeout(400)
    check(not p.is_visible('#toast.on'), 'previous toast cleared when adding again')
    for k in '45': c.tap(f'.key[data-k="{k}"]')
    c.tap('#saveBtn'); p.wait_for_timeout(400)
    check(len(items(p)) == 2, 'second entry saved')
    return c.close()

@test
def quick_log_again(b):
    c = Ctx(b); p = c.go(); setup(c)
    add(c, 20, 'food', 'Tea'); add(c, 20, 'food', 'Tea')
    chip = p.query_selector('.qchip')
    check(chip and 'Tea' in chip.inner_text(), 'repeat purchase offered')
    c.tap('.qchip'); p.wait_for_timeout(300)
    check(len([e for e in items(p) if e['n'] == 'Tea']) == 3, 'one tap logs it')
    return c.close()

@test
def keyboard_shortcuts(b):
    c = Ctx(b, mobile=False, viewport=(1280, 800)); p = c.go(); setup(c)
    p.keyboard.press('n'); p.wait_for_timeout(400)
    check(p.is_visible('#saveBtn'), 'N opens add')
    p.keyboard.type('75'); check(text(p, '#amtVal') == '75', 'typing digits')
    p.keyboard.press('Backspace'); p.keyboard.type('9')
    p.keyboard.press('Enter'); p.wait_for_timeout(400)
    check(len(items(p)) == 1 and items(p)[0]['a'] == 79, 'Enter saves')
    p.keyboard.press('n'); p.wait_for_timeout(350); p.keyboard.press('Escape'); p.wait_for_timeout(400)
    check(p.is_hidden('#sheet'), 'Escape closes')
    p.keyboard.press('n'); p.wait_for_timeout(350)
    p.click('#noteIn'); p.keyboard.type('12'); p.keyboard.press('Enter'); p.wait_for_timeout(300)
    check(len(items(p)) == 1 and text(p, '#amtVal') == '0', 'digits typed in the note stay in the note; Enter with no amount does nothing')
    return c.close()

# ------------------------------------------------------------------ robustness
@test
def survives_corrupted_storage(b):
    bad = {'daybook.v1': json.dumps({'settings': {'budget': 'abc', 'alertAt': 55, 'theme': 'neon', 'currency': 'XXX', 'limits': {'food': 'x', 'zzz': 5, 'fun': '200'}},
                                     'months': {'2026-10': [{'a': '50', 'c': 'bogus', 'd': '2026-10-03'}, {'a': -1, 'd': 'x'}, None, 'str', {'a': 10, 'd': '2026-13-45'}], 'bad': 5}})}
    c = Ctx(b, seed=bad, clock=datetime.datetime(2026, 10, 20, 12, 0)); p = c.go()
    c.tap('.tab[data-view="history"]')
    rows = p.query_selector_all('#histList .row')
    check(len(rows) == 1 and 'Gifts & Other' in rows[0].inner_text() and '₹50' in rows[0].inner_text(), 'keeps only the valid entry, as Other')
    c.tap('.tab[data-view="plan"]')
    check(p.get_attribute('[data-action="alert"][data-v="80"]', 'aria-pressed') == 'true', 'warning level repaired')
    check(p.get_attribute('[data-action="theme"][data-v="auto"]', 'aria-pressed') == 'true', 'theme repaired')
    check(p.input_value('#curSel') == 'INR' and p.input_value('input[data-limit="fun"]') == '200' and p.input_value('input[data-limit="food"]') == '', 'currency and limits repaired')
    for v in ['home', 'insights']: c.tap(f'.tab[data-view="{v}"]')
    add(c, 10, 'food')
    s = store(p)
    check(list(s['months'].keys()) == ['2026-10'] and len(s['months']['2026-10']) == 2, 'storage rewritten clean after next change ' + str(list(s['months'].keys())))
    errs = c.close()
    c2 = Ctx(b, seed={'daybook.v1': '{{{not json'}); p2 = c2.go()
    check(p2.is_visible('.welcome'), 'unreadable storage starts fresh')
    return errs + c2.close()

@test
def date_edges(b):
    errs = []
    for when, last_day in [(datetime.datetime(2026, 2, 28, 22, 0), True), (datetime.datetime(2028, 2, 29, 10, 0), True),
                           (datetime.datetime(2026, 12, 31, 23, 30), True), (datetime.datetime(2027, 1, 1, 0, 10), False),
                           (datetime.datetime(2026, 4, 30, 12, 0), True)]:
        c = Ctx(b, clock=when); p = c.go(); sample(c)
        sub = text(p, '.hero-sub')
        check(('today is the last day' in sub) == last_day, f'{when:%Y-%m-%d}: {sub}')
        c.tap('.tab[data-view="insights"]')
        check(p.is_disabled('[data-action="ins-next"]'), 'next disabled')
        n_days = len(p.query_selector_all('.dbar'))
        check(n_days == calendar.monthrange(when.year, when.month)[1], f'bars match month length {n_days}')
        c.tap('[data-action="ins-prev"]')
        c.tap('.tab[data-view="history"]'); c.tap('.tab[data-view="plan"]')
        errs += c.close()
    return errs

# ------------------------------------------------------------------ layout and iPhone
@test
def responsive_layouts(b):
    errs = []
    sizes = {'iphone-se-1': (320, 568), 'iphone-se': (375, 667), 'iphone-15': (393, 852), 'iphone-pro-max': (430, 932),
             'se-homescreen': (375, 647), '15-homescreen': (393, 798), 'max-homescreen': (430, 873), '15-safari-bars': (393, 659),
             'landscape': (852, 393), 'landscape-max': (932, 430), 'ipad': (820, 1180), 'ipad-landscape': (1180, 820),
             'desktop': (1280, 800), 'laptop-small': (1366, 768)}
    must_fit = ('iphone-se', 'iphone-15', 'iphone-pro-max', 'se-homescreen', '15-homescreen', 'max-homescreen', '15-safari-bars',
                'landscape-max', 'ipad', 'ipad-landscape', 'desktop', 'laptop-small')
    for name, (w, h) in sizes.items():
        mobile = name not in ('desktop', 'laptop-small')
        c = Ctx(b, mobile=mobile, viewport=(w, h)); p = c.go(); sample(c)
        for v in ['home', 'history', 'insights', 'plan']:
            c.tap(f'.tab[data-view="{v}"]'); p.wait_for_timeout(150)
            sw = p.evaluate('document.documentElement.scrollWidth'); iw = p.evaluate('window.innerWidth')
            check(sw <= w and iw == w, f'{name}/{v}: page wider than the {w}px screen (content {sw}, viewport {iw})')
            if name in ('iphone-se-1', 'iphone-15', 'landscape'): p.screenshot(path=f'{SHOTS}/{name}-{v}.png')
        c.tap('.tab[data-view="home"]')
        c.tap('.fab'); p.wait_for_timeout(450)
        box = p.query_selector('#saveBtn').bounding_box(); sheet = p.query_selector('#sheet').bounding_box()
        check(sheet['y'] >= -1 and sheet['y'] + sheet['height'] <= h + 1, f'{name}: sheet fits the screen {sheet}')
        check(box['y'] + box['height'] <= h + 1, f'{name}: Add button visible without scrolling ({box["y"] + box["height"]:.0f} > {h})')
        amt = p.query_selector('#amtBox').bounding_box()
        check(amt['y'] >= 0 and p.evaluate("document.getElementById('sheet').scrollTop") == 0, f'{name}: sheet opens at the top, amount visible')
        check(not p.is_visible('#toast.on'), f'{name}: no toast covering the keypad')
        h0 = p.query_selector('#amtBox').bounding_box()['height']
        c.tap('.key[data-k="5"]'); h1 = p.query_selector('#amtBox').bounding_box()['height']; c.tap('.key[data-k="del"]')
        check(abs(h0 - h1) < 1, f'{name}: amount display does not jump when typing ({h0} vs {h1})')
        if name in must_fit:
            fits = p.evaluate("(() => { const s = document.getElementById('sheet'); return s.scrollHeight <= s.clientHeight + 1; })()")
            check(fits, f'{name}: whole add screen fits without scrolling')
        key = p.query_selector('.key[data-k="1"]').bounding_box()
        check(key['height'] >= 38, f'{name}: keys large enough to tap ({key["height"]})')
        if name in ('desktop', 'ipad-landscape'):
            cp = p.evaluate("(() => { const e = document.getElementById('catPick'); return e.scrollWidth <= e.clientWidth + 1; })()")
            check(cp, f'{name}: all categories visible on a wide screen')
        if name in ('iphone-se-1', 'iphone-se', 'iphone-15', 'se-homescreen', 'landscape', 'ipad', 'desktop'):
            p.screenshot(path=f'{SHOTS}/{name}-add.png')
        errs += c.close()
    return errs

@test
def offline_launch_with_service_worker(b):
    c = Ctx(b, sw=True); p = c.go(800); setup(c)
    add(c, 60, 'travel', 'Auto')
    p.evaluate('navigator.serviceWorker.ready.then(() => true)')
    p.reload(); p.wait_for_timeout(800)
    check(p.evaluate('!!navigator.serviceWorker.controller'), 'service worker controls the page')
    c.ctx.set_offline(True)
    p.reload(); p.wait_for_timeout(800)
    check('Auto' in text(p, '#view-home') and p.title().startswith('Daybook'), 'opens offline with data')
    c.ctx.set_offline(False)
    return c.close()

@test
def ios_input_sizes_prevent_zoom(b):
    c = Ctx(b); p = c.go(); setup(c)
    c.tap('.fab'); p.wait_for_timeout(400)
    small = p.evaluate("""[...document.querySelectorAll('input,select,textarea')].filter(e => e.offsetParent !== null || e.id === 'dateIn').map(e => [e.id || e.className, parseFloat(getComputedStyle(e).fontSize)]).filter(x => x[1] < 16)""")
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    for v in ['history', 'plan']:
        c.tap(f'.tab[data-view="{v}"]')
        small += p.evaluate("""[...document.querySelectorAll('input,select')].filter(e => e.offsetParent !== null).map(e => [e.id || e.className, parseFloat(getComputedStyle(e).fontSize)]).filter(x => x[1] < 16)""")
    check(not small, 'inputs under 16px make iPhone zoom in: ' + str(small))
    meta = p.evaluate("[...document.querySelectorAll('meta')].map(m => (m.name || '') + '=' + (m.content || ''))")
    for need in ['apple-mobile-web-app-capable=yes', 'apple-mobile-web-app-title=Daybook']:
        check(need in meta, 'meta ' + need)
    check('viewport-fit=cover' in p.get_attribute('meta[name="viewport"]', 'content'), 'viewport-fit cover')
    for f in ['manifest.webmanifest', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png', 'icon-maskable-512.png', 'sw.js']:
        r = p.request.get(f'http://localhost:{PORT}/{f}'); check(r.ok, f'{f} served')
    man = p.request.get(f'http://localhost:{PORT}/manifest.webmanifest').json()
    check(man['display'] == 'standalone' and man['start_url'] == './', 'manifest ok')
    return c.close()

# ------------------------------------------------------------------ claude.ai version (simulated account)
@test
def cloud_fresh_account_sync(b):
    c = Ctx(b, claude=True); p = c.go(900)
    check(p.is_visible('.welcome'), 'welcome on empty account')
    setup(c, '20000'); p.wait_for_timeout(300)
    db = p.evaluate("JSON.parse(localStorage.getItem('__mockdb'))")
    check(db['data/users/u_test/settings']['budget'] == 20000, 'settings written to account')
    add(c, 150, 'food', 'Idli'); p.wait_for_timeout(300)
    db = p.evaluate("JSON.parse(localStorage.getItem('__mockdb'))")
    months = [k for k in db if '/m-' in k]
    check(len(months) == 1 and db[months[0]]['items'][0]['n'] == 'Idli', 'expense written to account')
    check(text(p, '#syncText') == 'Synced', 'sync label: ' + text(p, '#syncText'))
    p.evaluate("localStorage.removeItem('daybook.v1')")
    p.reload(); p.wait_for_timeout(900)
    check('Idli' in text(p, '#view-home') and p.is_hidden('#sheet'), 'data comes back from the account on a new device')
    c.tap('.tab[data-view="plan"]')
    check('Claude account' in text(p, '.data-status'), 'plan shows account storage')
    c.tap('[data-action="backup"]'); p.wait_for_timeout(300)
    dl = p.evaluate('window.__downloads')
    check(dl and dl[0]['filename'].endswith('.json'), 'backup uses the platform download prompt')
    return c.close()

@test
def cloud_migrates_browser_data(b):
    seed = {'daybook.v1': json.dumps({'v': 1, 'mode': 'local', 'settings': {'setup': True, 'budget': 15000, 'currency': 'INR', 'limits': {}},
                                      'months': {'2026-10': [{'id': 'x1', 'a': 99, 'c': 'food', 'n': 'Old', 'd': '2026-10-02', 'p': 'upi', 't': 1}]}})}
    c = Ctx(b, claude=True, seed=seed); p = c.go(900)
    db = p.evaluate("JSON.parse(localStorage.getItem('__mockdb') || '{}')")
    check(db.get('data/users/u_test/m-2026-10', {}).get('items', [{}])[0].get('n') == 'Old', 'browser data uploaded to the empty account')
    check(db['data/users/u_test/settings']['budget'] == 15000, 'settings uploaded')
    return c.close()

@test
def cloud_erased_elsewhere_clears_stale_copy(b):
    seed = {'daybook.v1': json.dumps({'v': 1, 'mode': 'cloud', 'settings': {'setup': True, 'budget': 15000},
                                      'months': {'2026-10': [{'id': 'x1', 'a': 99, 'c': 'food', 'n': 'Stale', 'd': '2026-10-02'}]}})}
    c = Ctx(b, claude=True, seed=seed); p = c.go(900)
    check('Stale' not in text(p, '#view-home') and p.is_visible('.welcome'), 'stale copy dropped when the account is empty')
    return c.close()

@test
def cloud_two_devices(b):
    c = Ctx(b, claude=True); p = c.go(900); setup(c, '25000'); add(c, 70, 'travel', 'Bus')
    p.wait_for_timeout(300)
    db = p.evaluate("localStorage.getItem('__mockdb')")
    c.close()
    c2 = Ctx(b, claude=True, seed={'__mockdb': db}); p2 = c2.go(900)
    check('Bus' in text(p2, '#view-home') and '25,000' in text(p2, '.hero-sub'), 'second device sees the same data')
    add(c2, 30, 'food', 'Chai'); p2.wait_for_timeout(300)
    db2 = p2.evaluate("JSON.parse(localStorage.getItem('__mockdb'))")
    m = [v for k, v in db2.items() if '/m-' in k][0]['items']
    check({e['n'] for e in m} == {'Bus', 'Chai'}, 'second device appends, nothing lost')
    return c2.close()

# ------------------------------------------------------------------ run
if __name__ == '__main__':
    only = sys.argv[1:]
    passed = failed = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        for fn in results:
            if only and fn.__name__ not in only: continue
            try:
                errs = fn(browser) or []
                if errs: raise AssertionError('browser errors: ' + '; '.join(errs[:5]))
                passed += 1; print(f'  PASS  {fn.__name__}')
            except Exception as e:
                failed += 1; print(f'  FAIL  {fn.__name__}: {e}')
                if not isinstance(e, AssertionError): traceback.print_exc()
        browser.close()
    print(f'\n{passed} passed, {failed} failed')
    httpd.shutdown()
    sys.exit(1 if failed else 0)
