"""
Claude Master — יצירת API Keys
הרץ: python setup/create_api_keys.py
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://platform.claude.com"

WORKSPACES = [
    {"name": "claude-master-admin",  "id": "wrkspc_01TwEh7KTEA753YKo4XB6J6s", "member": "Guy Neeman"},
    {"name": "team-lead-01",         "id": "wrkspc_01KN44oHJcxSPRyojkG8DeBV", "member": "Lilach Keynan"},
    {"name": "team-member-01",       "id": "wrkspc_01Q4QrM6oxssETW9cYNTpk6j", "member": "Barak Orbach"},
    {"name": "team-member-02",       "id": "wrkspc_017UEHsT2DeeYG8sWNNeRS7M", "member": "Roy Boker"},
    {"name": "team-member-03",       "id": "wrkspc_013PT8pmjmKaxhNrDcpsv79G", "member": "Adi Yehezkiel-Yaffe"},
    {"name": "team-member-04",       "id": "wrkspc_01GG3pqYDhX5tUrbuDUYyMqy", "member": "Dana Hasson"},
    {"name": "team-member-05",       "id": "wrkspc_014ZfRArfvCyyxD5C8txK93Q", "member": "Hila Cohen"},
    {"name": "team-member-06",       "id": "wrkspc_01BRRpM7st7ctGCGCbBD5Jnx", "member": "Philippe Lipschutz"},
    {"name": "team-member-07",       "id": "wrkspc_01EfCXdpLMcGieDDmcCo8a9Q", "member": "Tamar Maoz Knaz"},
    {"name": "team-member-08",       "id": "wrkspc_01HVajKv55TAk6PGSvKRGxWA", "member": "Yafit Mor"},
]


def get_cookies():
    import browser_cookie3, os, sqlite3, shutil, tempfile
    chrome_base = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    for profile in os.listdir(chrome_base):
        db = os.path.join(chrome_base, profile, "Cookies")
        if not os.path.exists(db):
            continue
        try:
            tmp = tempfile.mktemp(suffix=".db")
            shutil.copy2(db, tmp)
            conn = sqlite3.connect(tmp)
            n = conn.execute("SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%claude%'").fetchone()[0]
            conn.close()
            os.unlink(tmp)
            if n > 0:
                raw = list(browser_cookie3.chrome(cookie_file=db, domain_name=".claude.com"))
                raw += list(browser_cookie3.chrome(cookie_file=db, domain_name=".claude.ai"))
                return [{"name": c.name, "value": c.value,
                         "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
                         "path": c.path or "/", "secure": bool(c.secure),
                         "httpOnly": False, "sameSite": "Lax"} for c in raw]
        except Exception:
            continue
    return []


def create_key(page, key_name):
    """יוצר key אחד — מחזיר את ה-key value או None"""
    # ניווט נקי לדף
    page.goto(f"{BASE}/settings/keys")
    page.wait_for_load_state("networkidle")

    # פתח דיאלוג
    page.locator("button").filter(has_text="Create").first.click()

    # המתן לshדה שם
    field = page.locator('input[placeholder*="secret" i]').first
    field.wait_for(timeout=8000)
    field.fill(key_name)
    page.wait_for_timeout(400)

    # לחץ submit
    page.locator("button[type='submit']").first.click()
    page.wait_for_timeout(2000)
    page.screenshot(path="setup/key_dialog.png")

    # קרא key — innerText + input values
    import re
    try:
        page.wait_for_function("""() => {
            const pattern = /sk-ant-api03-[A-Za-z0-9_\\-]{80,}/;
            if (pattern.test(document.body.innerText)) return true;
            for (const inp of document.querySelectorAll('input')) {
                if (inp.value && pattern.test(inp.value)) return true;
            }
            return false;
        }""", timeout=10000)

        key = page.evaluate("""() => {
            const pattern = /sk-ant-api03-[A-Za-z0-9_\\-]{80,}/;
            const m = document.body.innerText.match(pattern);
            if (m) return m[0];
            for (const inp of document.querySelectorAll('input')) {
                const m2 = (inp.value || '').match(pattern);
                if (m2) return m2[0];
            }
            return null;
        }""")
        if key:
            return key
    except Exception:
        pass
    return None


def close_dialog(page):
    """סוגר דיאלוג בכל מצב"""
    try:
        page.locator("button").filter(has_text="Done").first.click(timeout=2000)
        page.wait_for_timeout(500)
        return
    except Exception:
        pass
    try:
        page.locator("button").filter(has_text="Close").first.click(timeout=1000)
        page.wait_for_timeout(500)
        return
    except Exception:
        pass
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


def main():
    cookies = get_cookies()
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        if cookies:
            ctx.add_cookies(cookies)
        page = ctx.new_page()

        # בדיקת session
        page.goto(f"{BASE}/settings/keys")
        page.wait_for_load_state("networkidle")
        if "/login" in page.url:
            print("⚠️  התחבר ידנית בדפדפן → Enter")
            input("Enter ► ")
            page.goto(f"{BASE}/settings/keys")
            page.wait_for_load_state("networkidle")
        print(f"✓ {page.url}\n")

        for ws in WORKSPACES:
            print(f"→ {ws['member']}", end="  ", flush=True)
            key = create_key(page, f"key-{ws['name']}")
            if key:
                print(f"✓ {key[:24]}...")
                results.append({**ws, "api_key": key})
            else:
                page.screenshot(path=f"setup/err_{ws['name']}.png")
                print("✗ נכשל")
                results.append({**ws, "api_key": "ERROR"})
            close_dialog(page)

        browser.close()

    out = Path("setup/workspaces_created.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    ok = sum(1 for r in results if r["api_key"].startswith("sk-"))
    print(f"\n✅ {ok}/{len(results)} keys → {out}")


if __name__ == "__main__":
    main()
