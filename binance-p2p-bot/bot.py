#!/usr/bin/env python3
"""
Binance P2P → Telegram Bot
Cada N minutos consulta el precio de compra de USDT con Bolívares (VES)
en Binance P2P, genera una imagen tipo tarjeta y la envía a un canal/grupo.

Variables de entorno requeridas:
  TELEGRAM_BOT_TOKEN  -> token de @BotFather
  TELEGRAM_CHAT_ID    -> ID del canal/grupo (ej: -1001234567890) o @nombre_canal

Opcionales:
  INTERVAL_MINUTES    -> intervalo de envío (default: 10)
  ROWS                -> cantidad de anuncios a mostrar (default: 5)
  TRADE_TYPE          -> BUY (comprar USDT) o SELL (vender USDT). Default: BUY
  PAY_TYPES           -> métodos de pago separados por coma, ej: "PagoMovil,Banesco" (default: todos)
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
TRADE_TYPE = os.environ.get("TRADE_TYPE", "BUY").upper()  # BUY = comprar USDT
PAY_TYPES = [p.strip() for p in os.environ.get("PAY_TYPES", "").split(",") if p.strip()]

P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
TZ = ZoneInfo("America/Caracas")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("p2p-bot")


# ---------------- Binance P2P ----------------
def fetch_p2p_ads() -> list[dict]:
    """Consulta la API pública de Binance P2P y devuelve los anuncios."""
    payload = {
        "asset": "USDT",
        "fiat": "VES",
        "tradeType": TRADE_TYPE,
        "page": 1,
        "rows": ROWS,
        "payTypes": PAY_TYPES,
        "publisherType": None,
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


# ---------------- Imagen ----------------
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold
        else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_image(ads: list[dict]) -> bytes:
    """Genera una tarjeta PNG con los precios."""
    W = 900
    header_h, row_h, footer_h = 210, 78, 60
    H = header_h + row_h * len(ads) + footer_h

    bg, card, accent = (14, 17, 22), (24, 29, 38), (240, 185, 11)  # binance yellow
    green, white, gray = (14, 203, 129), (234, 236, 239), (132, 142, 156)

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    now = datetime.now(TZ)
    accion = "COMPRA" if TRADE_TYPE == "BUY" else "VENTA"

    # Header
    d.rectangle([0, 0, W, header_h - 20], fill=card)
    d.rectangle([0, 0, W, 6], fill=accent)
    d.text((40, 28), "BINANCE P2P", font=_font(34, True), fill=accent)
    d.text((40, 78), f"USDT / VES  ·  {accion}", font=_font(24), fill=gray)

    best = ads[0]["price"] if ads else 0
    best_txt = f"{best:,.2f} Bs"
    f_big = _font(54, True)
    tw = d.textlength(best_txt, font=f_big)
    d.text((W - 40 - tw, 40), best_txt, font=f_big, fill=green)
    lbl = "mejor precio"
    f_lbl = _font(20)
    d.text((W - 40 - d.textlength(lbl, font=f_lbl), 108), lbl, font=f_lbl, fill=gray)

    d.text((40, 130), now.strftime("%d/%m/%Y  %I:%M %p (VET)"), font=_font(22), fill=white)

    # Filas
    y = header_h
    f_price, f_name, f_meta = _font(30, True), _font(24, True), _font(18)
    for i, ad in enumerate(ads):
        if i % 2 == 0:
            d.rectangle([0, y, W, y + row_h], fill=(19, 23, 31))
        d.text((40, y + 12), f"{i+1}", font=_font(24, True), fill=accent)
        d.text((90, y + 8), ad["merchant"][:22], font=f_name, fill=white)
        meta = f"{ad['orders']} órdenes · {ad['completion']}%"
        if ad["methods"]:
            meta += " · " + ", ".join(ad["methods"][:2])
        d.text((90, y + 42), meta[:70], font=f_meta, fill=gray)
        p = f"{ad['price']:,.2f} Bs"
        d.text((W - 40 - d.textlength(p, font=f_price), y + 22), p, font=f_price, fill=green)
        y += row_h

    # Footer
    d.text((40, y + 16), "Fuente: API pública Binance P2P · Actualización automática", font=_font(18), fill=gray)

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


def build_caption(ads: list[dict]) -> str:
    now = datetime.now(TZ).strftime("%d/%m/%Y %I:%M %p")
    accion = "Compra" if TRADE_TYPE == "BUY" else "Venta"
    if not ads:
        return f"⚠️ Sin datos de Binance P2P · {now} (VET)"
    return (
        f"💵 <b>{accion} USDT/VES — Binance P2P</b>\n"
        f"🏆 Mejor precio: <b>{ads[0]['price']:,.2f} Bs</b>\n"
        f"🕐 {now} (VET)"
    )


# ---------------- Loop principal ----------------
def run_once() -> None:
    ads = fetch_p2p_ads()
    if not ads:
        log.warning("La API no devolvió anuncios.")
        return
    photo = render_image(ads)
    send_photo(photo, build_caption(ads))
    log.info("Enviado. Mejor precio: %.2f Bs", ads[0]["price"])


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        sys.exit("ERROR: define TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID como variables de entorno.")
    if "--once" in sys.argv:  # modo cron (GitHub Actions, crontab, etc.)
        run_once()
        return
    log.info("Bot iniciado. Intervalo: %d min · TradeType: %s", INTERVAL_MINUTES, TRADE_TYPE)
    while True:
        try:
            run_once()
        except Exception:
            log.exception("Error en el ciclo; reintento en el próximo intervalo.")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
