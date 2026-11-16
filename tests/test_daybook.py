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
    def __init__(self, browser, mobile=True, viewport=(390, 844), claude=False, seed=None, clock=None, sw=False, tours=False):
        opts = dict(viewport={'width': viewport[0], 'height': viewport[1]}, service_workers='allow' if sw else 'block', accept_downloads=True)
        if mobile:
            opts.update(device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=IPHONE_UA)
        self.ctx = browser.new_context(**opts)
        if not tours:
            # the guided tours cover the page; only the tour tests turn them on
            self.ctx.add_init_script("try { const p = JSON.parse(localStorage.getItem('daybook.prefs') || '{}'); if (!p.tours) { p.tours = {guide: 1, news: 1, pick: 1}; localStorage.setItem('daybook.prefs', JSON.stringify(p)); } } catch (e) {}")
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

def add(c, amount, cat=None, note=None, when=None, pay=None, group=None):
    p = c.page
    c.tap('.fab'); p.wait_for_selector('#saveBtn', state='visible'); p.wait_for_timeout(350)
    for k in str(amount): c.tap(f'.key[data-k="{k}"]')
    if cat: c.tap(f'.cp[data-cat="{cat}"]')
    if note: p.fill('#noteIn', note)
    if when: c.tap(f'[data-action="pick-date"]:has-text("{when}")')
    if pay: c.tap(f'[data-action="pick-pay"][data-v="{pay}"]')
    if group is not None: p.select_option('#grpSel', group)
    c.tap('#saveBtn'); p.wait_for_timeout(400)

def make_group(c, name, icon=None, target=None, in_budget=True):
    p = c.page
    c.tap('.tab[data-view="plan"]')
    c.tap('[data-action="grp-new"]'); p.wait_for_selector('#gName', state='visible'); p.wait_for_timeout(350)
    p.fill('#gName', name)
    if icon: c.tap(f'[data-action="grp-icon"][data-v="{icon}"]')
    if target: p.fill('#gTarget', str(target))
    if not in_budget: c.tap('[data-action="grp-budget"]')
    c.tap('[data-action="grp-save"]'); p.wait_for_timeout(400)
    return [g for g in store(p)['settings']['groups'] if g['name'] == name][-1]

def state(settings, months):
    return {'daybook.v1': json.dumps({'v': 1, 'mode': 'local', 'settings': settings, 'months': months})}

def ex(id, a, c, d, n='', g=None):
    e = {'id': id, 'a': a, 'c': c, 'n': n, 'd': d, 'p': 'upi', 't': 1}
    if g: e['g'] = g
    return e

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
    check(raw[0] == 'Date,Category,Type,Note,Amount,Currency,Paid with,Group', 'csv header: ' + raw[0])
    check(raw[1].endswith(',Eating Out & Snacks,Wants,"Dosa, ""masala""",120,INR,UPI,'), 'csv row escaping: ' + raw[1])
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

# ------------------------------------------------------------------ groups, monthly income, welcome amounts
@test
def group_kept_out_of_budget(b):
    c = Ctx(b, clock=datetime.datetime(2026, 11, 16, 10, 0)); p = c.go(); setup(c, '30000')
    g = make_group(c, 'New car', '🚗', '800000', in_budget=False)
    check(g['apart'] and g['target'] == 800000 and g['icon'] == '🚗' and not g['done'], 'group saved ' + str(g))
    check('Created New car' in toast(p), 'created toast: ' + toast(p))
    check('New car' in text(p, '#planGroups') and 'outside budget' in text(p, '#planGroups'), 'listed in Plan')
    c.tap('.tab[data-view="home"]')
    check('₹0 of ₹8,00,000' in text(p, '#view-home'), 'Home shows the group before any spending')
    c.tap('.fab'); p.wait_for_selector('#grpSel', state='visible'); p.wait_for_timeout(350)
    check(p.input_value('#grpSel') == '', 'a new expense starts with no group')
    for k in '200000': c.tap(f'.key[data-k="{k}"]')
    c.tap('.cp[data-cat="other"]')
    p.select_option('#grpSel', g['id']); p.wait_for_timeout(100)
    hint = text(p, '#sheetHint')
    check('₹6,00,000 left of the ₹8,00,000 New car plan' in hint and 'Outside your budget' in hint, 'hint: ' + hint)
    check('over' not in p.get_attribute('#saveBtn', 'class') and 'on' in p.get_attribute('#grpSel', 'class'), 'not over, picker highlighted')
    p.fill('#noteIn', 'Down payment')
    c.tap('#saveBtn'); p.wait_for_timeout(400)
    check('outside your monthly budget' in toast(p), 'toast: ' + toast(p))
    it = items(p); check(len(it) == 1 and it[0]['g'] == g['id'], 'stored with its group ' + str(it))
    check('₹30,000' in text(p, '.hero-num') and 'left' in text(p, '.hero-num'), 'budget untouched: ' + text(p, '.hero-num'))
    check('Spent today\n₹0' in text(p, '.trio'), 'spent today leaves it out: ' + text(p, '.trio'))
    check('Categories appear here as you spend' in text(p, '#view-home'), 'no category spending counted')
    home = text(p, '#view-home')
    check('₹2,00,000 of ₹8,00,000' in home and '₹6,00,000 left of plan · outside your budget' in home, 'group progress on Home')
    check(text(p, '.list .row-sub').startswith('🚗 New car · '), 'recent row names the group: ' + text(p, '.list .row-sub'))
    c.tap(f'.cat-row[data-cat="g:{g["id"]}"]'); p.wait_for_timeout(300)
    check(p.is_visible('#view-history') and p.get_attribute(f'#histChips [data-cat="g:{g["id"]}"]', 'aria-pressed') == 'true', 'Home row opens filtered History')
    card = text(p, '.gcard')
    check('of ₹8,00,000 planned' in card and 'Kept out of your monthly budget' in card, 'group card: ' + card)
    c.tap('[data-action="add-grp"]'); p.wait_for_selector('#saveBtn', state='visible'); p.wait_for_timeout(350)
    check(p.input_value('#grpSel') == g['id'], 'Add to New car preselects the group')
    for k in '5000': c.tap(f'.key[data-k="{k}"]')
    c.tap('#saveBtn'); p.wait_for_timeout(400)
    check(len(p.query_selector_all('#histList .row')) == 2 and '₹2,05,000 spent' in text(p, '.mhead'), 'History lists and totals the group')
    c.tap('[data-action="add-grp"]'); p.wait_for_timeout(400)
    for k in '600000': c.tap(f'.key[data-k="{k}"]')
    check('₹5,000 past the ₹8,00,000 New car plan' in text(p, '#sheetHint') and 'anyway' in text(p, '#saveBtn'), 'over the plan warns: ' + text(p, '#sheetHint'))
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    c.tap('#histChips [data-cat="all"]'); p.fill('#histSearch', 'new car')
    check(len(p.query_selector_all('#histList .row')) == 2, 'search finds expenses by group name')
    c.tap('.tab[data-view="insights"]')
    ins = text(p, '#view-insights')
    check('Not counted on this page: ₹2,05,000 for 🚗 New car' in ins and 'Spent\n₹0' in ins, 'Insights leaves it out and says so')
    return c.close()

@test
def group_counted_in_budget(b):
    c = Ctx(b); p = c.go(); setup(c, '30000')
    g = make_group(c, 'Goa trip', '🏖️', '10000')
    check(not g['apart'], 'counts in the budget by default')
    c.tap('.tab[data-view="home"]')
    add(c, 6000, 'travel', 'Flights', group=g['id'])
    check('Added ₹6,000 to Travel & Commute, in Goa trip.' == toast(p), 'toast: ' + toast(p))
    check('₹24,000' in text(p, '.hero-num'), 'counts against the budget: ' + text(p, '.hero-num'))
    check('₹6,000' in text(p, '.cat-row[data-cat="travel"]'), 'and in its category')
    add(c, 5000, 'fun', 'Water sports', group=g['id'])
    check('Goa trip is now ₹1,000 past its ₹10,000 plan' in toast(p), 'plan crossing toast: ' + toast(p))
    row = p.query_selector(f'.cat-row[data-cat="g:{g["id"]}"]')
    check('over' in row.get_attribute('class') and '₹1,000 over plan' in row.inner_text(), 'Home row turns red over plan')
    add(c, 40, 'food', 'Tea')
    check(text(p, '#toastText') == 'Added ₹40 to Eating Out & Snacks.', 'ungrouped expense unaffected')
    return c.close()

@test
def group_edit_finish_and_delete(b):
    c = Ctx(b); p = c.go(); setup(c)
    g = make_group(c, 'Wedding', '💍')
    c.tap('.tab[data-view="home"]')
    add(c, 1500, 'shopping', 'Saree', group=g['id'])
    add(c, 300, 'food', 'Tea')
    c.tap('.list .row:has-text("Tea")'); p.wait_for_selector('#grpSel', state='visible'); p.wait_for_timeout(300)
    p.select_option('#grpSel', g['id']); c.tap('#saveBtn'); p.wait_for_timeout(400)
    check(all(e.get('g') == g['id'] for e in items(p)), 'editing an expense moves it into a group')
    c.tap('.list .row:has-text("Tea")'); p.wait_for_timeout(400)
    p.select_option('#grpSel', ''); c.tap('#saveBtn'); p.wait_for_timeout(400)
    check('g' not in [e for e in items(p) if e['n'] == 'Tea'][0], 'and out again')
    c.tap('.tab[data-view="plan"]'); c.tap(f'[data-action="grp-edit"][data-id="{g["id"]}"]'); p.wait_for_timeout(400)
    check(p.input_value('#gName') == 'Wedding' and p.get_attribute('[data-action="grp-icon"][data-v="💍"]', 'aria-checked') == 'true', 'edit sheet prefilled')
    p.fill('#gName', '   '); c.tap('[data-action="grp-save"]')
    check('Give the group a name' in text(p, '#gErr') and p.is_visible('#gName'), 'a name is required')
    p.fill('#gName', 'Sister’s wedding'); c.tap('[data-action="grp-save"]'); p.wait_for_timeout(400)
    check(store(p)['settings']['groups'][0]['name'] == 'Sister’s wedding' and toast(p) == 'Group saved', 'renamed')
    c.tap(f'[data-action="grp-edit"][data-id="{g["id"]}"]'); p.wait_for_timeout(400)
    c.tap('[data-action="grp-done"]'); p.wait_for_timeout(400)
    check(store(p)['settings']['groups'][0]['done'], 'marked as finished')
    check('finished' in text(p, '#planGroups'), 'Plan shows it as finished')
    c.tap('.tab[data-view="home"]')
    check(not p.query_selector(f'.cat-row[data-cat="g:{g["id"]}"]'), 'finished group leaves Home')
    c.tap('.fab'); p.wait_for_timeout(400)
    check(not p.query_selector('#grpSel'), 'and the add screen')
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    c.tap('.list .row:has-text("Saree")'); p.wait_for_timeout(400)
    check(p.input_value('#grpSel') == g['id'], 'an expense in a finished group still shows it when edited')
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    c.tap('.tab[data-view="history"]')
    check(p.query_selector(f'#histChips [data-cat="g:{g["id"]}"]'), 'finished group with expenses stays in History')
    c.tap('.tab[data-view="plan"]'); c.tap(f'[data-action="grp-edit"][data-id="{g["id"]}"]'); p.wait_for_timeout(400)
    check(text(p, '[data-action="grp-done"]') == 'Reopen group', 'can reopen')
    c.tap('[data-action="grp-done"]'); p.wait_for_timeout(400)
    check(not store(p)['settings']['groups'][0]['done'], 'reopened')
    c.tap(f'[data-action="grp-edit"][data-id="{g["id"]}"]'); p.wait_for_timeout(400)
    c.tap('[data-action="grp-delete"]')
    check('Tap again' in text(p, '[data-action="grp-delete"]'), 'delete asks twice')
    c.tap('[data-action="grp-delete"]'); p.wait_for_timeout(400)
    s = store(p)
    check(s['settings']['groups'] == [] and len(items(p)) == 2 and all('g' not in e for e in items(p)), 'group deleted, expenses kept')
    check('Its expenses are kept' in toast(p), 'delete toast: ' + toast(p))
    c.tap('#toastBtn'); p.wait_for_timeout(300)
    check(len(store(p)['settings']['groups']) == 1 and [e for e in items(p) if e['n'] == 'Saree'][0].get('g') == g['id'], 'undo brings the group back')
    return c.close()

@test
def income_differs_by_month(b):
    months = {'2026-09': [ex('a1', 2000, 'groceries', '2026-09-05')], '2026-10': [ex('a2', 3000, 'groceries', '2026-10-05')], '2026-11': [ex('a3', 1000, 'food', '2026-11-02')]}
    c = Ctx(b, seed=state({'setup': True, 'budget': 30000}, months), clock=datetime.datetime(2026, 11, 16, 10, 0)); p = c.go()
    c.tap('.tab[data-view="plan"]')
    check(text(p, 'label[for="incomeIn"]') == 'Income for November', 'label names the month')
    check(p.input_value('#incomeIn') == '' and p.get_attribute('#incomeIn', 'placeholder') == 'Optional', 'no income yet')
    p.fill('#incomeIn', '60000'); p.dispatch_event('#incomeIn', 'change')
    check(store(p)['settings']['incomes'] == {'2026-11': 60000}, 'saved for November: ' + str(store(p)['settings'].get('incomes')))
    check('Saved for November only' in text(p, '#incNote'), 'note: ' + text(p, '#incNote'))
    c.tap('.tab[data-view="insights"]')
    check('₹60,000 income for November,' in text(p, '#insIncome') and p.query_selector('#insIncome .guide'), 'November uses its own income')
    c.tap('[data-action="ins-prev"]')
    check('Add your income for October' in text(p, '#insIncome') and not p.query_selector('#insIncome .guide'), 'October is not given November’s income')
    c.tap('#insIncome [data-action="income-edit"]'); p.wait_for_selector('#incIn', state='visible'); p.wait_for_timeout(350)
    check(text(p, '#sheetTitle') == 'Income for October 2026', 'sheet title: ' + text(p, '#sheetTitle'))
    p.fill('#incIn', '52,500'); c.tap('[data-action="income-save"]'); p.wait_for_timeout(400)
    check(toast(p) == 'Income for October saved.', 'toast: ' + toast(p))
    check(store(p)['settings']['incomes'] == {'2026-10': 52500, '2026-11': 60000}, 'each month separate')
    check('₹52,500 income for October,' in text(p, '#insIncome'), 'October shows its own')
    c.tap('[data-action="ins-next"]')
    check('₹60,000 income for November,' in text(p, '#insIncome'), 'November unchanged by October')
    c.tap('[data-action="ins-prev"]'); c.tap('[data-action="ins-prev"]')
    check('Add your income for September' in text(p, '#insIncome'), 'nothing carried backward to September')
    p.keyboard.press('Escape')
    return c.close()

@test
def income_carries_forward(b):
    months = {'2026-10': [ex('a1', 3000, 'groceries', '2026-10-05')], '2026-11': [ex('a2', 1000, 'food', '2026-11-02')]}
    c = Ctx(b, seed=state({'setup': True, 'budget': 30000, 'incomes': {'2026-10': 50000}}, months), clock=datetime.datetime(2026, 11, 16, 10, 0)); p = c.go()
    c.tap('.tab[data-view="plan"]')
    check(p.input_value('#incomeIn') == '' and p.get_attribute('#incomeIn', 'placeholder') == '50,000', 'carried amount shown as a hint, not saved')
    check('Using October’s ₹50,000 until you change it' in text(p, '#incNote'), 'note: ' + text(p, '#incNote'))
    c.tap('.tab[data-view="insights"]')
    check('₹50,000 income for November, carried over from October' in text(p, '#insIncome'), 'Insights says it was carried: ' + text(p, '#insIncome'))
    c.tap('.tab[data-view="plan"]')
    p.fill('#incomeIn', '55000'); p.dispatch_event('#incomeIn', 'change')
    check(store(p)['settings']['incomes'] == {'2026-10': 50000, '2026-11': 55000}, 'a raise only changes November')
    p.fill('#incomeIn', ''); p.dispatch_event('#incomeIn', 'change')
    check(store(p)['settings']['incomes'] == {'2026-10': 50000} and 'Using October’s' in text(p, '#incNote'), 'clearing goes back to the carried amount')
    p.click('body'); p.wait_for_timeout(200)
    c.tap('[data-action="income-edit"][data-k="2026-10"]'); p.wait_for_selector('#incIn', state='visible'); p.wait_for_timeout(350)
    check(p.input_value('#incIn') == '50,000', 'last month’s sheet prefilled')
    p.fill('#incIn', ''); c.tap('[data-action="income-save"]'); p.wait_for_timeout(400)
    check(toast(p) == 'Income for October cleared.' and store(p)['settings']['incomes'] == {}, 'cleared: ' + toast(p))
    errs = c.close()
    for when, saved, label, carried in [(datetime.datetime(2026, 12, 3, 9, 0), {'2026-11': 61000}, 'December', 'November’s ₹61,000'),
                                        (datetime.datetime(2027, 1, 5, 9, 0), {'2026-12': 70000}, 'January', 'December’s ₹70,000')]:
        c = Ctx(b, seed=state({'setup': True, 'budget': 30000, 'incomes': saved}, {}), clock=when); p = c.go()
        c.tap('.tab[data-view="plan"]')
        check(text(p, 'label[for="incomeIn"]') == f'Income for {label}' and f'Using {carried}' in text(p, '#incNote'), f'{label}: ' + text(p, '#incNote'))
        errs += c.close()
    return errs

@test
def income_from_older_version(b):
    months = {'2026-09': [ex('a1', 2000, 'groceries', '2026-09-05')], '2026-10': [ex('a2', 3000, 'groceries', '2026-10-05')], '2026-11': [ex('a3', 1000, 'food', '2026-11-02')]}
    c = Ctx(b, seed=state({'setup': True, 'budget': 30000, 'income': 45000}, months), clock=datetime.datetime(2026, 11, 16, 10, 0)); p = c.go()
    c.tap('.tab[data-view="insights"]')
    check('₹45,000 income for November, your usual amount' in text(p, '#insIncome'), 'the single old income still applies: ' + text(p, '#insIncome'))
    c.tap('[data-action="ins-prev"]'); c.tap('[data-action="ins-prev"]')
    check('₹45,000 income for September, your usual amount' in text(p, '#insIncome'), 'to every month')
    c.tap('.tab[data-view="plan"]')
    check(p.get_attribute('#incomeIn', 'placeholder') == '45,000' and 'Using your usual ₹45,000' in text(p, '#incNote'), 'Plan: ' + text(p, '#incNote'))
    p.fill('#incomeIn', '50000'); p.dispatch_event('#incomeIn', 'change')
    s = store(p)['settings']
    check(s['incomes'] == {'2026-09': 45000, '2026-11': 50000} and s['income'] == 0, 'old income kept for earlier months: ' + str(s))
    c.tap('.tab[data-view="insights"]'); c.tap('[data-action="ins-next"]')
    check('₹45,000 income for October, carried over from September' in text(p, '#insIncome'), 'October keeps the old amount: ' + text(p, '#insIncome'))
    return c.close()

@test
def welcome_known_amounts(b):
    c = Ctx(b); p = c.go()
    p.wait_for_selector('#wBudget', state='visible')
    check(p.is_hidden('#wMore'), 'amounts are tucked away until asked for')
    c.tap('[data-action="welcome-more"]')
    check(p.is_visible('#wMore') and p.get_attribute('[data-action="welcome-more"]', 'aria-expanded') == 'true', 'expands')
    order = p.eval_on_selector_all('[data-wlimit]', 'els => els.map(e => e.dataset.wlimit)')
    check(order[:2] == ['rent', 'card'] and order[-2:] == ['invest', 'savings'] and len(order) == 14, 'fixed payments first, goals last: ' + str(order))
    p.fill('#wBudget', '40000')
    p.fill('input[data-wlimit="rent"]', '15000'); p.fill('input[data-wlimit="card"]', '8,000'); p.fill('input[data-wlimit="savings"]', '5000')
    check('₹23,000 of your ₹40,000 budget, leaving ₹17,000' in text(p, '#wSum'), 'running total leaves out goals: ' + text(p, '#wSum'))
    p.fill('#wBudget', '20000')
    check('warn' in p.get_attribute('#wSum', 'class') and '₹3,000 more than your budget' in text(p, '#wSum'), 'warns when over the budget')
    p.fill('#wBudget', '40000')
    p.select_option('#wCur', 'USD'); p.wait_for_timeout(100)
    check(text(p, '.wsym') == '$' and '$23,000' in text(p, '#wSum'), 'currency change updates the amounts')
    p.select_option('#wCur', 'INR'); p.wait_for_timeout(100)
    p.screenshot(path=f'{SHOTS}/welcome-amounts.png')
    c.tap('[data-action="welcome-start"]'); p.wait_for_timeout(400)
    s = store(p)['settings']
    check(s['limits'] == {'rent': 15000, 'card': 8000, 'savings': 5000} and s['budget'] == 40000, 'saved as limits ' + str(s['limits']))
    check(toast(p) == 'Budget and 3 monthly amounts saved. Change them anytime in Plan.', 'toast: ' + toast(p))
    check('₹0 of ₹15,000' in text(p, '.cat-row[data-cat="rent"]') and '₹0 of ₹5,000' in text(p, '.cat-row[data-cat="savings"]'), 'Home shows them')
    c.tap('.tab[data-view="plan"]')
    check(p.input_value('input[data-limit="card"]') == '8,000', 'Plan shows them')
    errs = c.close()
    c = Ctx(b); p = c.go(); p.wait_for_selector('#wBudget', state='visible')
    c.tap('[data-action="welcome-more"]'); p.fill('input[data-wlimit="rent"]', '9000')
    c.tap('[data-action="welcome-start"]'); p.wait_for_timeout(400)
    check(store(p)['settings']['limits'] == {'rent': 9000} and toast(p) == '1 monthly amount saved. Change them anytime in Plan.', 'amounts without a budget: ' + toast(p))
    return errs + c.close()

@test
def groups_and_income_in_backups(b):
    c = Ctx(b, mobile=False, clock=datetime.datetime(2026, 11, 16, 10, 0)); p = c.go(); setup(c)
    g = make_group(c, 'New car', '🚗', '500000', in_budget=False)
    p.fill('#incomeIn', '70000'); p.dispatch_event('#incomeIn', 'change')
    c.tap('.tab[data-view="home"]')
    add(c, 1000, 'other', 'Booking', group=g['id'])
    c.tap('.tab[data-view="plan"]')
    with p.expect_download() as d:
        c.tap('[data-action="backup"]')
    path = d.value.path(); data = json.load(open(path))
    check(data['settings']['groups'][0]['name'] == 'New car' and data['settings']['incomes'] == {'2026-11': 70000}, 'backup has groups and income')
    with p.expect_download() as d2:
        c.tap('[data-action="export"]')
    rows = open(d2.value.path(), encoding='utf-8-sig').read().splitlines()
    check(rows[1].endswith(',Booking,1000,INR,UPI,New car'), 'CSV names the group: ' + rows[1])
    c.tap('[data-action="erase"]'); c.tap('[data-action="erase"]'); p.wait_for_timeout(500)
    check(store(p)['settings']['groups'] == [] and store(p)['settings']['incomes'] == {}, 'erase clears groups and income')
    p.set_input_files('#restoreIn', path); p.wait_for_timeout(500)
    s = store(p)
    check(s['settings']['groups'][0]['id'] == g['id'] and s['settings']['incomes'] == {'2026-11': 70000} and items(p)[0].get('g') == g['id'], 'restored with groups and income')
    check('₹1,000 of ₹5,00,000' in text(p, '#view-home') and '₹30,000' in text(p, '.hero-num'), 'group still kept out of the budget after restore')
    p.set_input_files('#restoreIn', path); p.wait_for_timeout(400)
    check(len(store(p)['settings']['groups']) == 1, 'restoring twice does not duplicate groups')
    return c.close()

# ------------------------------------------------------------------ guided tours
def tour_check(p, w, h, sel, tag):
    card = p.query_selector('#tourCard').bounding_box()
    check(card['x'] >= 0 and card['y'] >= 0 and card['x'] + card['width'] <= w + 1 and card['y'] + card['height'] <= h + 1, f'{tag}: tour card on screen {card}')
    if sel:
        hole, t = p.query_selector('#tourHole').bounding_box(), p.query_selector(sel).bounding_box()
        check(hole['x'] <= t['x'] + 1 and hole['x'] + hole['width'] >= t['x'] + t['width'] - 1 and hole['y'] <= t['y'] + 1 and hole['y'] + hole['height'] > t['y'],
              f'{tag}: spotlight on {sel} ({hole} vs {t})')
    check(p.evaluate('document.documentElement.scrollWidth') <= w, f'{tag}: no sideways scroll')

@test
def tour_after_welcome(b):
    errs = []
    steps = [('home', '.hero', 'Your month at a glance'), ('home', '.fab', 'Log an expense'),
             ('plan', '#incomeIn', 'Income, month by month'), ('plan', '#planGroups', 'Groups for big plans')]
    for name in ('iphone-15', 'iphone-se-1', 'landscape'):
        w, h = SIZES[name]
        c = Ctx(b, viewport=(w, h), tours=True); p = c.go(); setup(c, '30000'); p.wait_for_timeout(300)
        check(p.is_visible('#tourCard'), f'{name}: tour starts after the welcome')
        for i, (v, sel, title) in enumerate(steps):
            tag = f'{name} step {i + 1}'
            check(text(p, '#tourTitle') == title and text(p, '.tour-step') == f'{i + 1} of 4', f'{tag}: ' + text(p, '#tourTitle'))
            check(p.is_visible(f'#view-{v}'), f'{tag}: shows {v}')
            tour_check(p, w, h, sel, tag)
            p.screenshot(path=f'{SHOTS}/tour-{name}-{i + 1}.png')
            if i == 1:
                c.tap('[data-action="tour-back"]')
                check(text(p, '#tourTitle') == steps[0][2], f'{tag}: Back goes to the previous step')
                c.tap('[data-action="tour-next"]')
            if i == 3: check(text(p, '[data-action="tour-next"]') == 'Done', 'last step says Done')
            c.tap('[data-action="tour-next"]'); p.wait_for_timeout(120)
        check(not p.query_selector('#tour') and p.is_visible('#view-home'), f'{name}: tour closes and returns Home')
        check(p.evaluate("JSON.parse(localStorage.getItem('daybook.prefs')).tours.guide") == 1, 'remembered on this device')
        add(c, 50, 'food', 'Tea')
        check(len(items(p)) == 1, f'{name}: app works normally after the tour')
        p.reload(); p.wait_for_timeout(800)
        check(not p.query_selector('#tour'), f'{name}: shown only once')
        errs += c.close()
    c = Ctx(b, tours=True); p = c.go(); sample(c); p.wait_for_timeout(300)
    check(p.is_visible('#tourCard') and not p.is_visible('#toast.on'), 'sample month also starts the tour')
    c.tap('[data-action="tour-end"]'); p.wait_for_timeout(150)
    check(not p.query_selector('#tour') and 'sample month' in toast(p), 'skipping shows the sample-month note: ' + toast(p))
    return errs + c.close()

@test
def tour_whats_new_for_existing_users(b):
    months = {'2026-11': [ex('a1', 400, 'food', '2026-11-02', 'Lunch')]}
    c = Ctx(b, tours=True, seed=state({'setup': True, 'budget': 30000, 'theme': 'dark'}, months), clock=datetime.datetime(2026, 11, 16, 10, 0)); p = c.go(1000)
    check(p.is_visible('#tourCard') and text(p, '#tourTitle') == 'New in Daybook' and text(p, '.tour-step') == '1 of 3', 'existing users get a what’s-new tour')
    check(p.is_hidden('#tourHole') and 'dim' in p.get_attribute('#tour', 'class'), 'the intro card has no spotlight')
    tour_check(p, 390, 844, None, 'what’s new intro')
    p.screenshot(path=f'{SHOTS}/tour-news-dark-1.png')
    p.keyboard.press('n'); p.wait_for_timeout(300)
    check(p.is_hidden('#sheet'), 'shortcuts are paused during a tour')
    p.keyboard.press('ArrowRight'); p.wait_for_timeout(150)
    check(text(p, '#tourTitle') == 'Income, month by month' and p.is_visible('#view-plan'), 'arrow key moves on')
    p.screenshot(path=f'{SHOTS}/tour-news-dark-2.png')
    p.keyboard.press('Escape'); p.wait_for_timeout(150)
    check(not p.query_selector('#tour') and p.is_visible('#view-home'), 'Escape ends the tour where it started')
    check(p.evaluate("JSON.parse(localStorage.getItem('daybook.prefs')).tours.news") == 1, 'skipping counts as seen')
    p.reload(); p.wait_for_timeout(1000)
    check(not p.query_selector('#tour'), 'not shown again')
    c.tap('.tab[data-view="plan"]'); c.tap('[data-action="tour-replay"]'); p.wait_for_timeout(150)
    check(text(p, '#tourTitle') == 'Your month at a glance' and p.is_visible('#view-home'), 'Plan can replay the tour')
    c.tap('[data-action="tour-end"]'); p.wait_for_timeout(150)
    check(not p.query_selector('#tour') and p.is_visible('#view-plan'), 'skipping a replay returns to Plan')
    return c.close()

@test
def tour_group_picker_tip(b):
    seed = state({'setup': True, 'budget': 30000, 'groups': [{'id': 'gcar', 'name': 'New car', 'icon': '🚗'}]}, {})
    seed['daybook.prefs'] = json.dumps({'tours': {'guide': 1, 'news': 1}})
    c = Ctx(b, tours=True, seed=seed); p = c.go()
    c.tap('.fab'); p.wait_for_timeout(700)
    check(p.is_visible('#tourCard') and text(p, '#tourTitle') == 'Add it to a group' and not p.query_selector('.tour-step'), 'one-step tip on the group picker')
    check(text(p, '[data-action="tour-next"]') == 'Got it' and not p.query_selector('[data-action="tour-end"]'), 'a single tip just says Got it')
    tour_check(p, 390, 844, '.grp-pick', 'picker tip')
    key = p.query_selector('.key[data-k="5"]').bounding_box()
    check(p.evaluate(f"!!document.elementFromPoint({key['x'] + 5}, {key['y'] + 5}).closest('#tour')"), 'the page underneath is blocked while the tip shows')
    p.screenshot(path=f'{SHOTS}/tour-picker-tip.png')
    c.tap('[data-action="tour-next"]'); p.wait_for_timeout(150)
    check(not p.query_selector('#tour') and p.is_visible('#saveBtn'), 'tip closes, sheet stays open')
    c.tap('.key[data-k="5"]')
    check(text(p, '#amtVal') == '5', 'keypad works after the tip')
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    c.tap('.fab'); p.wait_for_timeout(700)
    check(not p.query_selector('#tour'), 'the tip shows once')
    return c.close()

# ------------------------------------------------------------------ robustness
@test
def survives_corrupted_storage(b):
    bad = {'daybook.v1': json.dumps({'settings': {'budget': 'abc', 'alertAt': 55, 'theme': 'neon', 'currency': 'XXX', 'limits': {'food': 'x', 'zzz': 5, 'fun': '200'},
                                                  'incomes': {'2026-13': 5, '2026-10': '40000', 'soon': 9, '2026-09': 'n/a'},
                                                  'groups': [None, 'str', {'name': '   '}, {'id': 'g1', 'name': '  Car  ', 'icon': 'nope', 'target': 'abc', 'apart': 1}, {'id': 'g1', 'name': 'Dup'}]},
                                     'months': {'2026-10': [{'a': '50', 'c': 'bogus', 'd': '2026-10-03', 'g': 5}, {'a': -1, 'd': 'x'}, None, 'str', {'a': 10, 'd': '2026-13-45'}], 'bad': 5}})}
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
    check(all('g' not in e for e in s['months']['2026-10']), 'a broken group link is dropped')
    check(s['settings']['incomes'] == {'2026-10': 40000}, 'only valid months keep an income: ' + str(s['settings']['incomes']))
    check(s['settings']['groups'] == [{'id': 'g1', 'name': 'Car', 'icon': '🏷️', 'target': 0, 'apart': True, 'done': False}], 'groups repaired: ' + str(s['settings']['groups']))
    c.tap('.tab[data-view="insights"]')
    check('₹40,000 income for October' in text(p, '#insIncome'), 'repaired income used')
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
SIZES = {'iphone-se-1': (320, 568), 'iphone-se': (375, 667), 'iphone-15': (393, 852), 'iphone-pro-max': (430, 932),
         'se-homescreen': (375, 647), '15-homescreen': (393, 798), 'max-homescreen': (430, 873), '15-safari-bars': (393, 659),
         'landscape': (852, 393), 'landscape-max': (932, 430), 'ipad': (820, 1180), 'ipad-landscape': (1180, 820),
         'desktop': (1280, 800), 'laptop-small': (1366, 768)}
MUST_FIT = ('iphone-se', 'iphone-15', 'iphone-pro-max', 'se-homescreen', '15-homescreen', 'max-homescreen', '15-safari-bars',
            'landscape-max', 'ipad', 'ipad-landscape', 'desktop', 'laptop-small')

@test
def responsive_layouts(b):
    errs = []
    sizes, must_fit = SIZES, MUST_FIT
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
def layouts_with_groups(b):
    # the add screen gains a group picker once groups exist; it must still fit, and the new screens must not overflow
    today = datetime.datetime(2026, 11, 16, 10, 0)
    groups = [{'id': 'gcar', 'name': 'New car', 'icon': '🚗', 'target': 800000, 'apart': True},
              {'id': 'gtrip', 'name': 'Goa trip with college friends', 'icon': '🏖️', 'target': 0}]
    months = {'2026-11': [ex('x1', 200000, 'other', '2026-11-03', 'Down payment', 'gcar'), ex('x2', 3200, 'travel', '2026-11-10', 'Flights', 'gtrip'),
                          ex('x3', 450, 'food', '2026-11-15', 'Dinner')]}
    settings = {'setup': True, 'budget': 44000, 'limits': {'food': 5000, 'rent': 12000}, 'incomes': {'2026-10': 65000}, 'groups': groups}
    errs = []
    for name, (w, h) in SIZES.items():
        mobile = name not in ('desktop', 'laptop-small')
        for theme in (['light', 'dark'] if name == 'iphone-15' else ['light']):
            c = Ctx(b, mobile=mobile, viewport=(w, h), clock=today, seed=state(dict(settings, theme=theme), months)); p = c.go()
            tag = f'{name}-dark' if theme == 'dark' else name
            shots = name in ('iphone-se-1', 'iphone-15', 'landscape')
            for v in ['home', 'history', 'plan']:
                c.tap(f'.tab[data-view="{v}"]'); p.wait_for_timeout(150)
                if v == 'history': c.tap('#histChips [data-cat="g:gcar"]')
                if v == 'home': p.evaluate("document.querySelector('.cat-row[data-cat=\"g:gcar\"]').scrollIntoView({block: 'center'})")
                if v == 'plan': p.evaluate("document.getElementById('planGroups').scrollIntoView()")
                sw = p.evaluate('document.documentElement.scrollWidth')
                check(sw <= w, f'{tag}/{v}: page wider than the screen ({sw} > {w})')
                if shots: p.screenshot(path=f'{SHOTS}/groups-{tag}-{v}.png')
            c.tap('.tab[data-view="home"]')
            c.tap('.fab'); p.wait_for_timeout(450)
            p.select_option('#grpSel', 'gtrip'); p.wait_for_timeout(50)
            p.select_option('#grpSel', 'gcar')
            for k in '200000': c.tap(f'.key[data-k="{k}"]')
            note, pick = p.query_selector('#noteIn').bounding_box(), p.query_selector('#grpSel').bounding_box()
            check(abs(note['y'] - pick['y']) < 1 and note['width'] >= 140, f'{tag}: note and group picker share a row ({note}, {pick})')
            check(pick['x'] + pick['width'] <= p.query_selector('#sheet').bounding_box()['x'] + p.query_selector('#sheet').bounding_box()['width'], f'{tag}: picker inside the sheet')
            box = p.query_selector('#saveBtn').bounding_box()
            check(box['y'] + box['height'] <= h + 1, f'{tag}: Add button visible with a group picked')
            if name in MUST_FIT:
                fits = p.evaluate("(() => { const s = document.getElementById('sheet'); return s.scrollHeight <= s.clientHeight + 1 && s.scrollWidth <= s.clientWidth + 1; })()")
                check(fits, f'{tag}: add screen with a group still fits without scrolling')
            if shots: p.screenshot(path=f'{SHOTS}/groups-{tag}-add.png')
            c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
            c.tap('.tab[data-view="plan"]')
            c.tap('#planGroups [data-action="grp-edit"][data-id="gcar"]'); p.wait_for_timeout(450)
            check(p.evaluate("(() => { const s = document.getElementById('sheet'); return s.scrollWidth <= s.clientWidth + 1; })()"), f'{tag}: group sheet has no sideways scroll')
            if shots: p.screenshot(path=f'{SHOTS}/groups-{tag}-group-sheet.png')
            c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
            c.tap('#view-plan [data-action="income-edit"]'); p.wait_for_timeout(450)
            sheet = p.query_selector('#sheet').bounding_box(); save = p.query_selector('[data-action="income-save"]').bounding_box()
            check(save['y'] + save['height'] <= sheet['y'] + sheet['height'] + 1, f'{tag}: income sheet fits')
            if shots: p.screenshot(path=f'{SHOTS}/groups-{tag}-income-sheet.png')
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
    sizes_js = """[...document.querySelectorAll('input,select,textarea')].filter(e => e.offsetParent !== null || e.id === 'dateIn').map(e => [e.id || e.className, parseFloat(getComputedStyle(e).fontSize)]).filter(x => x[1] < 16)"""
    c = Ctx(b); p = c.go()
    p.wait_for_selector('#wBudget', state='visible'); c.tap('[data-action="welcome-more"]')
    small = p.evaluate(sizes_js)
    check(len(p.query_selector_all('[data-wlimit]')) == 14, 'welcome amounts checked')
    setup(c)
    make_group(c, 'Trip')
    c.tap('[data-action="grp-new"]'); p.wait_for_timeout(400)
    small += p.evaluate(sizes_js)
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    c.tap('[data-action="income-edit"]'); p.wait_for_timeout(400)
    small += p.evaluate(sizes_js)
    c.tap('[data-action="sheet-close"]'); p.wait_for_timeout(400)
    c.tap('.tab[data-view="home"]')
    c.tap('.fab'); p.wait_for_timeout(400)
    check(p.is_visible('#grpSel'), 'group picker checked')
    small += p.evaluate(sizes_js)
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

@test
def cloud_syncs_groups_and_income(b):
    when = datetime.datetime(2026, 11, 16, 10, 0)
    c = Ctx(b, claude=True, clock=when); p = c.go(900); setup(c, '25000')
    g = make_group(c, 'Goa trip', '🏖️', in_budget=False)
    p.fill('#incomeIn', '40000'); p.dispatch_event('#incomeIn', 'change')
    c.tap('.tab[data-view="home"]')
    add(c, 900, 'travel', 'Bus to Goa', group=g['id']); p.wait_for_timeout(300)
    raw = p.evaluate("localStorage.getItem('__mockdb')"); db = json.loads(raw)
    st = db['data/users/u_test/settings']
    check(st['groups'][0]['name'] == 'Goa trip' and st['groups'][0]['apart'] and st['incomes'] == {'2026-11': 40000}, 'settings doc carries groups and income')
    check(db['data/users/u_test/m-2026-11']['items'][0]['g'] == g['id'], 'expense doc carries the group')
    errs = c.close()
    c2 = Ctx(b, claude=True, clock=when, seed={'__mockdb': raw}); p2 = c2.go(900)
    check('₹900 this month · outside your budget' in text(p2, '#view-home') and '₹25,000' in text(p2, '.hero-num'), 'second device sees the group, kept out of the budget')
    c2.tap('.tab[data-view="insights"]')
    check('₹40,000 income for November' in text(p2, '#insIncome'), 'second device sees the income')
    return errs + c2.close()

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
