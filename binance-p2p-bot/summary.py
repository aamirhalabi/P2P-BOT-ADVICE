#!/usr/bin/env python3
"""
Resumen diario USDT/VES — lee el historial guardado por bot.py y publica
en Telegram un resumen del día anterior: apertura, cierre, variación %,
máximo/mínimo con horas, promedios, spread y gráfico de la curva del día.
 
Usa las mismas variables de entorno que bot.py:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Opcional:
  HISTORY_FILE   -> ruta del CSV (default: data/history.csv)
  SUMMARY_DATE   -> fecha a resumir YYYY-MM-DD (default: ayer en VET)
"""
 
import csv
import io
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
 
import requests
from PIL import Image, ImageDraw, ImageFont
 
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
HISTORY_FILE = os.environ.get("HISTORY_FILE", "data/history.csv")
TZ = ZoneInfo("America/Caracas")
 
BG = (14, 17, 22)
CARD = (24, 29, 38)
ACCENT = (240, 185, 11)
GREEN = (14, 203, 129)
RED = (246, 70, 93)
WHITE = (234, 236, 239)
GRAY = (132, 142, 156)
 
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
 
 
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()
 
 
def fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
 
 
def load_day(date_str: str) -> list[dict]:
    """Carga las filas del historial correspondientes a una fecha (VET)."""
    rows = []
    if not os.path.exists(HISTORY_FILE):
        return rows
    with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                if ts.strftime("%Y-%m-%d") != date_str or not r.get("buy"):
                    continue
                rows.append(
                    {
                        "ts": ts,
                        "buy": float(r["buy"]),
                        "sell": float(r["sell"]) if r.get("sell") else None,
                        "spread": float(r["spread"]) if r.get("spread") else None,
                        "liq_buy": float(r["liq_buy"]) if r.get("liq_buy") else None,
                        "liq_sell": float(r["liq_sell"]) if r.get("liq_sell") else None,
                        "banks": [b for b in (r.get("banks") or "").split("|") if b],
                    }
                )
            except (ValueError, KeyError):
                continue
    rows.sort(key=lambda x: x["ts"])
    return rows
 
 
def draw_chart(d: ImageDraw.ImageDraw, rows: list[dict], x: int, y: int, w: int, h: int) -> None:
    """Curva del precio de compra durante el día."""
    d.rectangle([x, y, x + w, y + h], fill=CARD)
    prices = [r["buy"] for r in rows]
    lo, hi = min(prices), max(prices)
    pad = (hi - lo) * 0.12 or hi * 0.002 or 1
    lo, hi = lo - pad, hi + pad
    px, py, pw, ph = x + 70, y + 18, w - 100, h - 56
 
    # Ejes / referencias
    f_ax = _font(15)
    for frac in (0.0, 0.5, 1.0):
        val = hi - (hi - lo) * frac
        yy = py + ph * frac
        d.line([px, yy, px + pw, yy], fill=(40, 46, 58), width=1)
        d.text((x + 12, yy - 9), fmt(val), font=f_ax, fill=GRAY)
 
    # Línea de precio
    t0 = rows[0]["ts"].timestamp()
    t1 = rows[-1]["ts"].timestamp() or t0 + 1
    pts = []
    for r in rows:
        fx = px + pw * ((r["ts"].timestamp() - t0) / max(t1 - t0, 1))
        fy = py + ph * (1 - (r["buy"] - lo) / (hi - lo))
        pts.append((fx, fy))
    if len(pts) > 1:
        d.line(pts, fill=ACCENT, width=3)
    for p in (pts[0], pts[-1]):
        d.ellipse([p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5], fill=ACCENT)
 
    # Horas en el eje X
    for frac in (0.0, 0.5, 1.0):
        t = datetime.fromtimestamp(t0 + (t1 - t0) * frac, TZ)
        label = t.strftime("%I:%M %p").lstrip("0")
        xx = px + pw * frac - d.textlength(label, font=f_ax) / 2
        d.text((xx, y + h - 28), label, font=f_ax, fill=GRAY)
 
 
def fmt_usdt(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M".replace(".", ",")
    if v >= 1_000:
        return f"{v/1_000:.0f}K"
    return f"{v:.0f}"
 
 
def bank_ranking(rows: list[dict], top: int = 5) -> list[tuple[str, float]]:
    """Bancos más presentes en los primeros anuncios del día (% de apariciones)."""
    counts: dict[str, int] = {}
    total = 0
    for r in rows:
        for b in r["banks"]:
            counts[b] = counts.get(b, 0) + 1
            total += 1
    if not total:
        return []
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return [(b, c / total * 100) for b, c in ranked]
 
 
def render_summary(date_str: str, rows: list[dict]) -> bytes:
    banks = bank_ranking(rows)
    W = 980
    # header 142 + 3 filas de tarjetas (324) + gráfico (16+32+280) + bancos + footer
    H = 824 + ((36 + len(banks) * 44 + 10) if banks else 0) + 64
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
 
    day = datetime.strptime(date_str, "%Y-%m-%d")
    fecha = f"{DIAS[day.weekday()].capitalize()}, {day.day} de {MESES[day.month - 1]} {day.year}"
 
    # Header
    d.rectangle([0, 0, W, 118], fill=CARD)
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    d.text((40, 22), "RESUMEN DEL DÍA", font=_font(32, True), fill=ACCENT)
    d.text((40, 70), f"USDT / VES · Binance P2P · {fecha}", font=_font(20), fill=GRAY)
 
    buys = [r["buy"] for r in rows]
    open_p, close_p = buys[0], buys[-1]
    hi_i = max(range(len(buys)), key=lambda i: buys[i])
    lo_i = min(range(len(buys)), key=lambda i: buys[i])
    var = (close_p - open_p) / open_p * 100
    avg = sum(buys) / len(buys)
    spreads = [r["spread"] for r in rows if r["spread"] is not None]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0
    var_color = RED if var > 0 else GREEN  # sube el dólar = rojo (se devalúa el Bs)
    var_sign = "+" if var > 0 else ""
 
    # Variación destacada
    v_txt = f"{var_sign}{fmt(var)}%"
    f_v = _font(46, True)
    d.text((W - 40 - d.textlength(v_txt, font=f_v), 30), v_txt, font=f_v, fill=var_color)
 
    # Liquidez ofertada (proxy de volumen)
    liq_b = [r["liq_buy"] for r in rows if r["liq_buy"]]
    liq_s = [r["liq_sell"] for r in rows if r["liq_sell"]]
    liq_buy_txt = f"{fmt_usdt(sum(liq_b)/len(liq_b))} USDT" if liq_b else "—"
    liq_sell_txt = f"{fmt_usdt(sum(liq_s)/len(liq_s))} USDT" if liq_s else "—"
 
    # Tarjetas de stats (3 filas x 3)
    stats = [
        ("Apertura", f"{fmt(open_p)} Bs", WHITE),
        ("Cierre", f"{fmt(close_p)} Bs", WHITE),
        ("Promedio", f"{fmt(avg)} Bs", WHITE),
        ("Máximo", f"{fmt(buys[hi_i])} Bs · {rows[hi_i]['ts'].strftime('%I:%M %p').lstrip('0')}", RED),
        ("Mínimo", f"{fmt(buys[lo_i])} Bs · {rows[lo_i]['ts'].strftime('%I:%M %p').lstrip('0')}", GREEN),
        ("Spread prom.", f"{fmt(avg_spread)} Bs", WHITE),
        ("Liquidez compra", liq_buy_txt, ACCENT),
        ("Liquidez venta", liq_sell_txt, ACCENT),
        ("Mediciones", str(len(rows)), WHITE),
    ]
    cw, ch, gx, gy = 286, 92, 21, 16
    x0, y0 = 40, 142
    f_lbl, f_val = _font(17), _font(23, True)
    for i, (lbl, val, color) in enumerate(stats):
        cx = x0 + (i % 3) * (cw + gx)
        cy = y0 + (i // 3) * (ch + gy)
        d.rectangle([cx, cy, cx + cw, cy + ch], fill=CARD)
        d.text((cx + 18, cy + 14), lbl, font=f_lbl, fill=GRAY)
        d.text((cx + 18, cy + 44), val, font=f_val, fill=color)
 
    # Gráfico
    chart_y = y0 + 3 * (ch + gy) + 16
    d.text((40, chart_y), "Comportamiento del precio de compra", font=_font(19, True), fill=WHITE)
    draw_chart(d, rows, 40, chart_y + 32, W - 80, 280)
 
    # Bancos más presentes
    by = chart_y + 32 + 280 + 30
    if banks:
        d.text((40, by), "Bancos más presentes en las primeras ofertas", font=_font(19, True), fill=WHITE)
        by += 36
        f_bank, f_pct = _font(18, True), _font(16)
        max_pct = banks[0][1] or 1
        for name, pct in banks:
            d.text((40, by + 6), name[:32], font=f_bank, fill=WHITE)
            bar_x, bar_w = 360, W - 360 - 110
            d.rectangle([bar_x, by + 6, bar_x + bar_w, by + 26], fill=CARD)
            d.rectangle([bar_x, by + 6, bar_x + bar_w * (pct / max_pct), by + 26], fill=ACCENT)
            d.text((bar_x + bar_w + 14, by + 6), f"{pct:.0f}%", font=f_pct, fill=GRAY)
            by += 44
 
    d.text((40, H - 44), f"Basado en {len(rows)} mediciones · Liquidez = USDT ofertados (promedio) · Fuente: Binance P2P",
           font=_font(16), fill=GRAY)
 
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
 
 
def send_photo(photo: bytes, caption: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
        files={"photo": ("resumen.png", photo, "image/png")},
        timeout=30,
    )
    r.raise_for_status()
 
 
def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        sys.exit("ERROR: define TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.")
 
    date_str = os.environ.get("SUMMARY_DATE") or (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = load_day(date_str)
    if len(rows) < 2:
        print(f"Sin datos suficientes para {date_str} ({len(rows)} filas); no se envía resumen.")
        return
 
    buys = [r["buy"] for r in rows]
    var = (buys[-1] - buys[0]) / buys[0] * 100
    sign = "+" if var > 0 else ""
    emoji = "📈" if var > 0 else "📉" if var < 0 else "➡️"
    day = datetime.strptime(date_str, "%Y-%m-%d")
    caption = (
        f"{emoji} <b>Resumen {DIAS[day.weekday()]} {day.day}/{day.month}</b>\n"
        f"Apertura: {fmt(buys[0])} Bs → Cierre: <b>{fmt(buys[-1])} Bs</b>\n"
        f"Variación: <b>{sign}{fmt(var)}%</b> · Máx: {fmt(max(buys))} · Mín: {fmt(min(buys))}"
    )
    send_photo(render_summary(date_str, rows), caption)
    print(f"Resumen de {date_str} enviado ({len(rows)} mediciones).")
 
 
if __name__ == "__main__":
    main()
