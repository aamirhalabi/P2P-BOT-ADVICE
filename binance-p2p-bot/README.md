# Binance P2P → Telegram Bot

Bot que cada 10 minutos envía a tu canal/grupo de Telegram una imagen con el precio
actual de **compra de USDT con Bolívares (VES)** en Binance P2P, usando la API pública
(sin riesgo de bloqueos ni captchas).

---

## 1. Crear el bot en Telegram

1. Abre Telegram y habla con **@BotFather**.
2. Envía `/newbot`, dale un nombre y un username (debe terminar en `bot`).
3. Copia el **token** que te da (formato `123456789:AAxx...`).

## 2. Conectar el bot a tu canal o grupo

1. Crea el canal/grupo (o usa uno existente).
2. Agrega tu bot como **administrador** con permiso de publicar mensajes.
3. Obtén el **chat ID**:
   - Canal público: puedes usar directamente `@nombre_del_canal`.
   - Canal/grupo privado: reenvía un mensaje del canal a **@userinfobot** o
     **@getidsbot**; el ID tiene formato `-100xxxxxxxxxx`.

## 3. Desplegar (elige una opción)

### Opción A — GitHub Actions (100% gratis, recomendada)

No necesitas servidor: GitHub ejecuta el script cada 10 minutos.

1. Crea un repositorio en GitHub y sube todos los archivos de esta carpeta
   (incluyendo `.github/workflows/p2p.yml`).
2. En el repo: **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` → tu token
   - `TELEGRAM_CHAT_ID` → tu chat ID
3. Ve a la pestaña **Actions**, habilita los workflows y ejecuta
   "Binance P2P → Telegram" manualmente (Run workflow) para probar.

> Nota: GitHub Actions puede tener retrasos de 3–10 min en horas pico; el intervalo
> real puede variar. Para precisión exacta usa la Opción B.

### Opción B — Railway / Render / VPS (proceso 24/7)

El bot corre en loop continuo (`python bot.py`). Incluye `Dockerfile`.

**Railway** (~5 USD/mes tras el crédito de prueba):
1. [railway.app](https://railway.app) → New Project → Deploy from GitHub repo.
2. Detecta el Dockerfile automáticamente.
3. En **Variables** agrega `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

**VPS con Docker:**
```bash
docker build -t p2p-bot .
docker run -d --restart=always \
  -e TELEGRAM_BOT_TOKEN=xxx \
  -e TELEGRAM_CHAT_ID=-100xxx \
  p2p-bot
```

### Opción C — Tu PC (prueba rápida)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=xxx
export TELEGRAM_CHAT_ID=-100xxx
python bot.py          # loop cada 10 min
python bot.py --once   # un solo envío (para probar)
```

## 4. Configuración opcional (variables de entorno)

| Variable | Default | Descripción |
|---|---|---|
| `INTERVAL_MINUTES` | `10` | Intervalo entre envíos (solo modo loop) |
| `ROWS` | `5` | Cantidad de anuncios en la imagen |
| `TRADE_TYPE` | `BUY` | `BUY` = comprar USDT, `SELL` = vender USDT |
| `PAY_TYPES` | todos | Filtrar por método de pago, ej: `PagoMovil,Banesco` |

## Estructura

```
binance-p2p-bot/
├── bot.py                    # lógica completa: API → imagen → Telegram
├── requirements.txt
├── Dockerfile                # para Railway/Render/VPS
├── .env.example
└── .github/workflows/p2p.yml # cron gratis en GitHub Actions
```
