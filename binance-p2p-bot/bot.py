#!/usr/bin/env python3
"""
Binance P2P (Comercio por Bloques) → Telegram Bot
Consulta los anuncios de COMPRA y VENTA de USDT/VES en el mercado de bloques
de Binance P2P (solo comerciantes verificados), genera una imagen con la
seguidilla de los primeros anuncios (precio, límites y disponibilidad)
y la envía a un canal/grupo de Telegram.
 
Variables de entorno requeridas:
  TELEGRAM_BOT_TOKEN  -> token de @BotFather
  TELEGRAM_CHAT_ID    -> ID del canal/grupo (ej: -1001234567890) o @nombre_canal
 
Opcionales:
  INTERVAL_MINUTES    -> intervalo en modo loop (default: 10)
  ROWS                -> anuncios por lado (default: 5)
  CLASSIFIES          -> mercado: "block" = comercio por bloques (default),
                         "mass,profession" = P2P normal
  PUBLISHER_TYPE      -> "merchant" = solo verificados (default), vacío = todos
  PAY_TYPES           -> métodos de pago separados por coma (default: todos)
"""
 
import io
import os
import sys
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
 
import requests
from PIL import Image, ImageDraw, ImageFont
 
# ---------------- Configuración ----------------
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))
ROWS = int(os.environ.get("ROWS", "5"))
CLASSIFIES_BUY = [c.strip() for c in os.environ.get("CLASSIFIES_BUY", "mass,profession").split(",") if c.strip()]
CLASSIFIES_SELL = [c.strip() for c in os.environ.get("CLASSIFIES_SELL", "mass,profession").split(",") if c.strip()]
PUBLISHER_TYPE = os.environ.get("PUBLISHER_TYPE", "merchant").strip() or None
PAY_TYPES = [p.strip() for p in os.environ.get("PAY_TYPES", "").split(",") if p.strip()]
MAX_DEV_PCT = float(os.environ.get("MAX_DEV_PCT", "3.0"))  # % máx. de desviación vs mediana
HISTORY_FILE = os.environ.get("HISTORY_FILE", "data/history.csv")
QUIET_START = os.environ.get("QUIET_START", "00:00")  # inicio del silencio (hora VET)
QUIET_END = os.environ.get("QUIET_END", "07:10")      # fin del silencio (hora VET)
 
P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
TZ = ZoneInfo("America/Caracas")
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("p2p-bot")
 
 
# ---------------- Binance P2P ----------------
def fetch_ads(trade_type: str, classifies: list[str]) -> list[dict]:
    """Consulta la API pública de Binance P2P y devuelve los anuncios."""
    payload = {
        "asset": "USDT",
        "fiat": "VES",
        "tradeType": trade_type,
        "page": 1,
        "rows": ROWS + 5,  # extra para poder descartar promocionados/outliers
        "payTypes": PAY_TYPES,
        "countries": [],
        "publisherType": PUBLISHER_TYPE,
        "classifies": classifies,
        "proMerchantAds": False,
        "shieldMerchantAds": False,
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    r = requests.post(P2P_URL, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json().get("data") or []
 
    ads = []
    for item in data:
        adv = item.get("adv", {})
        advertiser = item.get("advertiser", {})
        methods = [m.get("tradeMethodName") or m.get("identifier", "") for m in adv.get("tradeMethods", [])]
        ads.append(
            {
                "price": float(adv.get("price", 0)),
                "available": float(adv.get("surplusAmount", 0)),
                "min": float(adv.get("minSingleTransAmount", 0)),
                "max": float(adv.get("maxSingleTransAmount", 0)),
                "merchant": advertiser.get("nickName", "—"),
                "orders": advertiser.get("monthOrderCount", 0),
                "completion": round(float(advertiser.get("monthFinishRate", 0)) * 100, 1),
                "methods": [m for m in methods if m],
            }
        )
    return ads
 
 
def filter_promoted(ads: list[dict]) -> list[dict]:
    """Descarta anuncios promocionados/outliers: precios que se desvían
    más de MAX_DEV_PCT% de la mediana del grupo."""
    if len(ads) < 3:
        return ads[:ROWS]
    prices = sorted(a["price"] for a in ads)
    median = prices[len(prices) // 2]
    kept = [a for a in ads if abs(a["price"] - median) / median * 100 <= MAX_DEV_PCT]
    dropped = len(ads) - len(kept)
    if dropped:
        log.info("Descartados %d anuncios fuera de mercado (mediana %.2f).", dropped, median)
    return kept[:ROWS]
 
 
def fetch_side(trade_type: str) -> list[dict]:
    """COMPRA usa el mercado configurado en CLASSIFIES_BUY (bloques),
    VENTA usa CLASSIFIES_SELL (P2P normal). Con fallback si 'block' viene vacío."""
    classifies = CLASSIFIES_BUY if trade_type == "BUY" else CLASSIFIES_SELL
    ads = fetch_ads(trade_type, classifies)
    if not ads and classifies == ["block"]:
        log.warning("Sin anuncios en 'block' para %s; usando mercado normal.", trade_type)
        ads = fetch_ads(trade_type, ["mass", "profession"])
    return filter_promoted(ads)
 
 
# ---------------- Helpers ----------------
def fmt_bs(v: float) -> str:
    """Formatea montos en Bs de forma compacta: 36,45M / 500K / 797,00"""
    if v >= 1_000_000:
        return f"{v/1_000_000:,.2f}M".replace(",", "X").replace(".", ",").replace("X", ".")
    if v >= 1_000:
        return f"{v/1_000:,.0f}K".replace(",", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
 
 
def fmt_usdt(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")
 
 
def fmt_price(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
 
 
# ---------------- Imagen ----------------
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()
 
 
BG = (14, 17, 22)
CARD = (24, 29, 38)
ROW_ALT = (19, 23, 31)
ACCENT = (240, 185, 11)
GREEN = (14, 203, 129)
RED = (246, 70, 93)
WHITE = (234, 236, 239)
GRAY = (132, 142, 156)
 
 
def _section(d: ImageDraw.ImageDraw, x: int, y: int, w: int, title: str,
             color: tuple, ads: list[dict], row_h: int) -> int:
    """Dibuja una sección (Compra o Venta). Devuelve la Y final."""
    d.rectangle([x, y, x + w, y + 44], fill=CARD)
    d.rectangle([x, y, x + 6, y + 44], fill=color)
    d.text((x + 22, y + 8), title, font=_font(24, True), fill=color)
    if ads:
        ref = f"{fmt_price(ads[0]['price'])} Bs"
        f_ref = _font(24, True)
        d.text((x + w - 22 - d.textlength(ref, font=f_ref), y + 8), ref, font=f_ref, fill=WHITE)
    y += 52
 
    f_name, f_price = _font(22, True), _font(26, True)
    f_meta = _font(16)
    if not ads:
        d.text((x + 22, y + 10), "Sin anuncios disponibles", font=_font(20), fill=GRAY)
        return y + row_h
 
    for i, ad in enumerate(ads):
        if i % 2 == 0:
            d.rectangle([x, y, x + w, y + row_h], fill=ROW_ALT)
        d.text((x + 18, y + 10), f"{i+1}", font=_font(20, True), fill=ACCENT)
        d.text((x + 52, y + 8), ad["merchant"][:20], font=f_name, fill=WHITE)
        meta1 = f"Límite: {fmt_bs(ad['min'])} – {fmt_bs(ad['max'])} Bs"
        meta2 = f"Disp: {fmt_usdt(ad['available'])} USDT · {ad['orders']} órd. · {ad['completion']}%"
        banks = " · ".join(ad["methods"][:3]) if ad["methods"] else "—"
        if len(ad["methods"]) > 3:
            banks += f" (+{len(ad['methods']) - 3})"
        d.text((x + 52, y + 36), meta1, font=f_meta, fill=GRAY)
        d.text((x + 52, y + 56), meta2, font=f_meta, fill=GRAY)
        d.text((x + 52, y + 76), banks[:80], font=f_meta, fill=ACCENT)
        p = f"{fmt_price(ad['price'])} Bs"
        d.text((x + w - 18 - d.textlength(p, font=f_price), y + 22), p, font=f_price, fill=color)
        y += row_h
    return y
 
 
def render_image(buy_ads: list[dict], sell_ads: list[dict]) -> bytes:
    W = 980
    header_h, row_h, gap, footer_h = 150, 102, 26, 56
    n = max(len(buy_ads), 1)
    m = max(len(sell_ads), 1)
    H = header_h + (52 + n * row_h) + gap + (52 + m * row_h) + footer_h
 
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    now = datetime.now(TZ)
 
    # Header
    d.rectangle([0, 0, W, header_h - 24], fill=CARD)
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    d.text((40, 24), "BINANCE P2P", font=_font(32, True), fill=ACCENT)
    d.text((40, 72), "USDT / VES · Comerciantes verificados", font=_font(20), fill=GRAY)
 
    # Spread
    if buy_ads and sell_ads:
        spread = buy_ads[0]["price"] - sell_ads[0]["price"]
        s_txt = f"Spread: {fmt_price(spread)} Bs"
        f_s = _font(20, True)
        d.text((W - 40 - d.textlength(s_txt, font=f_s), 28), s_txt, font=f_s, fill=WHITE)
    t_txt = now.strftime("%d/%m/%Y %I:%M %p (VET)")
    f_t = _font(18)
    d.text((W - 40 - d.textlength(t_txt, font=f_t), 60), t_txt, font=f_t, fill=GRAY)
 
    y = header_h
    y = _section(d, 0, y, W, "COMPRA  (tú compras USDT)", GREEN, buy_ads, row_h)
    y += gap
    y = _section(d, 0, y, W, "VENTA  (tú vendes USDT)", RED, sell_ads, row_h)
 
    d.text((40, y + 14), "Fuente: API pública Binance P2P", font=_font(16), fill=GRAY)
 
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
 
 
# ---------------- Telegram ----------------
def send_photo(photo: bytes, caption: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
        files={"photo": ("p2p.png", photo, "image/png")},
        timeout=30,
    )
    r.raise_for_status()
 
 
def build_caption(buy_ads: list[dict], sell_ads: list[dict]) -> str:
    now = datetime.now(TZ).strftime("%d/%m/%Y %I:%M %p")
    lines = ["💵 <b>USDT/VES — Binance P2P</b>"]
    if buy_ads:
        lines.append(f"🟢 Compra: <b>{fmt_price(buy_ads[0]['price'])} Bs</b>")
    if sell_ads:
        lines.append(f"🔴 Venta: <b>{fmt_price(sell_ads[0]['price'])} Bs</b>")
    lines.append(f"🕐 {now} (VET)")
    return "\n".join(lines)
 
 
# ---------------- Historial ----------------
def save_history(buy_ads: list[dict], sell_ads: list[dict]) -> None:
    """Guarda un snapshot en CSV para el resumen diario."""
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE) or ".", exist_ok=True)
        new_file = not os.path.exists(HISTORY_FILE)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            if new_file:
                f.write("timestamp,buy,sell,spread,liq_buy,liq_sell,banks\n")
            now = datetime.now(TZ).isoformat(timespec="seconds")
            buy = buy_ads[0]["price"] if buy_ads else ""
            sell = sell_ads[0]["price"] if sell_ads else ""
            spread = (buy - sell) if (buy_ads and sell_ads) else ""
            liq_buy = round(sum(a["available"] for a in buy_ads)) if buy_ads else ""
            liq_sell = round(sum(a["available"] for a in sell_ads)) if sell_ads else ""
            banks = "|".join(
                m for a in (buy_ads + sell_ads) for m in a["methods"]
            ).replace(",", " ")
            f.write(f"{now},{buy},{sell},{spread},{liq_buy},{liq_sell},{banks}\n")
    except Exception:
        log.exception("No se pudo guardar el historial (no es crítico).")
 
 
def in_quiet_hours() -> bool:
    """True si la hora actual (VET) está dentro del horario silencioso."""
    try:
        s = datetime.strptime(QUIET_START, "%H:%M").time()
        e = datetime.strptime(QUIET_END, "%H:%M").time()
    except ValueError:
        return False
    if s == e:  # mismo valor = silencio desactivado
        return False
    t = datetime.now(TZ).time()
    if s <= e:
        return s <= t < e
    return t >= s or t < e  # rango que cruza medianoche
 
 
# ---------------- Loop principal ----------------
def run_once() -> None:
    if in_quiet_hours():
        log.info("Horario silencioso (%s–%s VET); no se envía.", QUIET_START, QUIET_END)
        return
    buy_ads = fetch_side("BUY")
    sell_ads = fetch_side("SELL")
    if not buy_ads and not sell_ads:
        log.warning("La API no devolvió anuncios en ningún lado.")
        return
    save_history(buy_ads, sell_ads)
    photo = render_image(buy_ads, sell_ads)
    send_photo(photo, build_caption(buy_ads, sell_ads))
    log.info(
        "Enviado. Compra: %s · Venta: %s",
        buy_ads[0]["price"] if buy_ads else "—",
        sell_ads[0]["price"] if sell_ads else "—",
    )
 
 
def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        sys.exit("ERROR: define TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID como variables de entorno.")
    if "--once" in sys.argv:  # modo cron (cron-job.org / GitHub Actions)
        run_once()
        return
    log.info("Bot iniciado. Intervalo: %d min", INTERVAL_MINUTES)
    while True:
        try:
            run_once()
        except Exception:
            log.exception("Error en el ciclo; reintento en el próximo intervalo.")
        time.sleep(INTERVAL_MINUTES * 60)
 
 
if __name__ == "__main__":
    main()
