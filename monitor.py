import asyncio, hashlib, json, os, re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BRAND_URL = os.getenv("PBANDAI_URL", "https://p-bandai.com/us/brand/onepiececardgame")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_MENTION = os.getenv("DISCORD_MENTION", "").strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
TIMEZONE_NAME = os.getenv("TIMEZONE", "America/Toronto")
STATE_FILE = Path(os.getenv("STATE_FILE", "state/state.json"))
TZ = ZoneInfo(TIMEZONE_NAME)
REMINDER_MINUTES = (1440, 60, 15, 5)

@dataclass
class Product:
    product_id: str
    title: str
    url: str
    image_url: Optional[str] = None
    preorder_at: Optional[str] = None
    status: str = "unknown"
    button_text: str = ""

def clean(v): return re.sub(r"\s+", " ", v or "").strip()
def now(): return datetime.now(timezone.utc)
def pid(url, title=""):
    m = re.search(r"/item/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else hashlib.sha256(f"{url}|{title}".encode()).hexdigest()[:24]
def load_state():
    if not STATE_FILE.exists():
        return {"initialized": False, "products": {}, "last_heartbeat_month": None}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))
def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, sort_keys=True), encoding="utf-8")
def parse_dt(v):
    if not v: return None
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
def dtime(d):
    t = int(d.timestamp())
    return f"<t:{t}:F> (<t:{t}:R>)"

def parse_preorder_time(text):
    text = clean(text)
    p = (r"(?:pre[- ]?order|orders?|sales?)\s*"
         r"(?:start|starts|open|opens|begin|begins|available from)"
         r"\s*[:\-]?\s*(.{0,130}?(?:AM|PM|am|pm)"
         r"(?:\s*(?:EDT|EST|ET|PDT|PST|PT|CDT|CST|CT))?)")
    m = re.search(p, text, re.I)
    if not m: return None
    c = clean(m.group(1))
    offsets = {"EDT":"-0400","EST":"-0500","CDT":"-0500","CST":"-0600","PDT":"-0700","PST":"-0800"}
    c = re.sub(r"\b(EDT|EST|CDT|CST|PDT|PST)\b", lambda x: offsets[x.group(1).upper()], c, flags=re.I)
    c = re.sub(r"\b(?:ET|CT|PT)\b", "", c, flags=re.I)
    try: d = dateparser.parse(c, fuzzy=True)
    except Exception: return None
    if not d: return None
    if d.tzinfo is None: d = d.replace(tzinfo=TZ)
    return d.astimezone(timezone.utc)

def detect_status(text, button):
    low = f"{clean(text)} {clean(button)}".lower()
    if any(x in low for x in ("sold out","out of stock","pre-orders closed","orders closed")): return "sold_out"
    if any(x in low for x in ("add to cart","pre-order now","preorder now","order now","in stock")): return "available"
    if any(x in low for x in ("coming soon","pre-order starts","preorder starts","orders start")): return "coming_soon"
    return "unknown"

def extract_products(html):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    def add(url, title="", image=None):
        if not url: return
        url = urljoin(BRAND_URL, url).split("#")[0]
        parsed = urlparse(url)
        if "p-bandai.com" not in parsed.netloc or "/item/" not in parsed.path: return
        title = clean(title) or "ONE PIECE CARD GAME product"
        p = Product(pid(url, title), title[:250], url, urljoin(BRAND_URL, image) if image else None)
        if p.product_id not in found or len(p.title) > len(found[p.product_id].title): found[p.product_id] = p
    for a in soup.select('a[href*="/item/"]'):
        img = a.find("img")
        image = (img.get("src") or img.get("data-src") or img.get("data-lazy-src")) if img else None
        alt = img.get("alt", "") if img else ""
        add(a.get("href",""), clean(a.get_text(" ", strip=True)) or clean(alt), image)
    for m in re.finditer(r"(?:https?:\\/\\/p-bandai\.com)?\\/us\\/item\\/[A-Za-z0-9_-]+|https?://p-bandai\.com/us/item/[A-Za-z0-9_-]+|/us/item/[A-Za-z0-9_-]+", html):
        add(m.group(0).replace("\\/","/"))
    return list(found.values())

async def page(browser):
    return await browser.new_page(viewport={"width":1440,"height":1400}, locale="en-US",
        timezone_id=TIMEZONE_NAME,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36")
async def html(page_obj, url):
    await page_obj.goto(url, wait_until="domcontentloaded", timeout=90000)
    try: await page_obj.wait_for_load_state("networkidle", timeout=25000)
    except PlaywrightTimeoutError: pass
    await page_obj.wait_for_timeout(3000)
    return await page_obj.content()

async def enrich(browser, p):
    pg = await page(browser)
    try:
        source = await html(pg, p.url)
        soup = BeautifulSoup(source, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        buttons = [clean(e.get_text(" ", strip=True)) for e in soup.select("button,a.btn,a.button,[role=button],.cart,.purchase,.order,.stock")]
        p.button_text = " | ".join(dict.fromkeys(x for x in buttons if x and len(x)<=120))[:500]
        p.status = detect_status(text, p.button_text)
        opening = parse_preorder_time(text)
        if opening: p.preorder_at = opening.isoformat()
        ogt = soup.select_one('meta[property="og:title"]')
        ogi = soup.select_one('meta[property="og:image"]')
        if ogt and clean(ogt.get("content","")): p.title = clean(ogt["content"])[:250]
        if ogi and ogi.get("content"): p.image_url = urljoin(p.url, ogi["content"])
        return p
    finally:
        await pg.close()

async def discord(title, desc, p=None, color=0x5865F2):
    if not WEBHOOK_URL: return
    embed = {"title":title[:256],"description":desc[:4096],"color":color,"footer":{"text":"P-Bandai Monitor — GitHub Actions"}}
    if p:
        embed["url"] = p.url
        if p.image_url: embed["thumbnail"]={"url":p.image_url}
    payload = {"username":"P-Bandai Preorder Alerts","content":DISCORD_MENTION or None,
               "allowed_mentions":{"parse":["roles","users","everyone"] if DISCORD_MENTION else []},
               "embeds":[embed]}
    async with httpx.AsyncClient() as c:
        r = await c.post(WEBHOOK_URL, json=payload, timeout=30); r.raise_for_status()

async def ntfy(title, desc, p=None):
    if not NTFY_TOPIC: return
    safe = re.sub(r"[^\x20-\x7E]+","",title).strip() or "P-Bandai Alert"
    headers = {"Title":safe,"Priority":"high"}
    if p: headers["Click"]=p.url
    async with httpx.AsyncClient() as c:
        r = await c.post(f"https://ntfy.sh/{NTFY_TOPIC}", content=desc.replace("**","").encode(), headers=headers, timeout=30)
        r.raise_for_status()

async def notify(title, desc, p=None, color=0x5865F2):
    results = await asyncio.gather(discord(title,desc,p,color), ntfy(title,desc,p), return_exceptions=True)
    for name,res in zip(("Discord","ntfy"),results):
        if isinstance(res,Exception): print(f"{name} failed: {res}")

async def run():
    state = load_state()
    first = not state.get("initialized",False)
    saved = state.setdefault("products",{})
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True,args=["--disable-blink-features=AutomationControlled"])
        pg = await page(browser)
        try:
            listing = await html(pg, BRAND_URL)
            products = extract_products(listing)
            if not products:
                await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await pg.wait_for_timeout(3000)
                products = extract_products(await pg.content())
            if not products: raise RuntimeError("No P-Bandai product links found")
            print(f"Found {len(products)} product(s)")
            for basic in products:
                try: cur = await enrich(browser,basic)
                except Exception as e:
                    print(f"Detail failed {basic.product_id}: {e}"); cur = basic
                prev = saved.get(cur.product_id)
                if prev is None:
                    saved[cur.product_id] = {**asdict(cur),"first_seen":now().isoformat(),"alerts_sent":[]}
                    if not first:
                        timing = f"\n\n**Opens:** {dtime(parse_dt(cur.preorder_at))}" if cur.preorder_at else ""
                        await notify("🆕 New public P-Bandai listing detected",f"**{cur.title}**{timing}\n\n[Open product page]({cur.url})",cur,0x57F287)
                else:
                    old_status = prev.get("status","unknown")
                    old_time = prev.get("preorder_at")
                    prev.update({k:v for k,v in asdict(cur).items() if v not in (None,"")})
                    if not old_time and cur.preorder_at:
                        await notify("📅 Preorder opening time detected",f"**{cur.title}**\n\n**Opens:** {dtime(parse_dt(cur.preorder_at))}",cur,0x3498DB)
                    if old_status in {"sold_out","unknown","coming_soon"} and cur.status=="available":
                        key=f"available:{cur.button_text}"
                        if key not in prev.setdefault("alerts_sent",[]):
                            await notify("🔥 Availability/restock detected",f"**{cur.title}** changed from `{old_status}` to **available**.\n\n[Open product page]({cur.url})",cur,0x9B59B6)
                            prev["alerts_sent"].append(key)
            current_now = now()
            for key,item in saved.items():
                opening = parse_dt(item.get("preorder_at"))
                if not opening: continue
                p = Product(key,item.get("title","ONE PIECE product"),item.get("url",BRAND_URL),item.get("image_url"),item.get("preorder_at"),item.get("status","unknown"),item.get("button_text",""))
                sent = item.setdefault("alerts_sent",[])
                if opening > current_now:
                    for mins in REMINDER_MINUTES:
                        akey=f"reminder:{mins}:{opening.isoformat()}"
                        if opening-timedelta(minutes=mins) <= current_now < opening and akey not in sent:
                            label="24 hours" if mins==1440 else "1 hour" if mins==60 else f"{mins} minutes"
                            await notify(f"⏰ Preorder opens in {label}",f"**{p.title}**\n\n**Opens:** {dtime(opening)}\n\n[Open product page]({p.url})",p,0xED4245 if mins<=15 else 0xFEE75C)
                            sent.append(akey)
                live=f"live:{opening.isoformat()}"
                if opening <= current_now < opening+timedelta(minutes=10) and live not in sent:
                    await notify("🚨 Preorder should be LIVE now",f"**{p.title}**\n\n[Open product page]({p.url})",p,0xED4245)
                    sent.append(live)
            month=datetime.now(TZ).strftime("%Y-%m")
            if state.get("last_heartbeat_month") != month:
                state["last_heartbeat_month"]=month
                await notify("💓 Monthly monitor heartbeat",f"Monitor is running.\n\n**Tracked products:** {len(saved)}",color=0x57F287)
            state["initialized"]=True
            state["last_check"]=current_now.isoformat()
            save_state(state)
        finally:
            await pg.close(); await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
