"""
servidor_local.py
Servidor local — Plazo Fijo BCRA + Dólar Bancos.
Expone API REST consumida por Vercel via Cloudflare Tunnel.

== INSTALACIÓN (una sola vez) ==
pip install playwright fastapi uvicorn requests beautifulsoup4
playwright install chromium

== USO ==
python servidor_local.py

== CLOUDFLARE TUNNEL ==
1. Descargar cloudflared.exe:
   https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
2. En otra ventana CMD:
   cloudflared.exe tunnel --url http://localhost:8000
3. Copiar la URL https://xxxx.trycloudflare.com
4. En Vercel → Settings → Environment Variables:
   LOCAL_SERVER_URL = https://xxxx.trycloudflare.com

== ENDPOINTS ==
GET /pf      → tasas plazo fijo BCRA
GET /dolar   → cotización dólar bancos
GET /health  → estado del servidor
"""

import asyncio
import os
import logging
import re
from datetime import datetime, date

import requests
import uvicorn
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright

# ── CONFIG ──
PORT = int(os.environ.get('PORT', '8080'))
PF_REFRESH_SECONDS    = 600   # PF: cada 10 minutos
DOLAR_REFRESH_SECONDS = 300   # Dólar: cada 5 minutos
HORA_INICIO = 9    # Horario hábil: 09:00 AR
HORA_FIN    = 18   # Horario hábil: 18:00 AR

def es_horario_habil() -> bool:
    """True si es lunes-viernes entre HORA_INICIO y HORA_FIN (hora Argentina)."""
    now = datetime.now()
    if now.weekday() >= 5:  # sábado=5, domingo=6
        return False
    return HORA_INICIO <= now.hour < HORA_FIN

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Dashboard Mercados — Servidor Local")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

# ════════════════════════════════════════════
# UTILIDADES
# ════════════════════════════════════════════

NOMBRE_CORTO = {
    "NACION": "Nación", "GALICIA": "Galicia", "PROVINCIA DE BUENOS": "Provincia BsAs",
    "PROVINCIA DE CORDOBA": "Prov. Córdoba", "PROVINCIA DE TIERRA": "Prov. T. del Fuego",
    "PROVINCIA": "Provincia", "BBVA": "BBVA", "SANTANDER": "Santander",
    "MACRO": "Macro", "CIUDAD": "Ciudad", "HIPOTECARIO": "Hipotecario",
    "HSBC": "HSBC", "ICBC": "ICBC", "INDUSTRIAL AND COMMERCIAL": "ICBC",
    "MERIDIAN": "Meridian", "PLUS": "Plus Cambio",
    "BRUBANK": "Brubank", "PATAGONIA": "Patagonia", "SUPERVIELLE": "Supervielle",
    "CREDICOOP": "Credicoop", "COMAFI": "Comafi", "BIND": "BIND",
    "NARANJA": "Naranja X", "VOII": "VOII", "DEL SOL": "Banco del Sol",
    "CMF": "CMF", "BICA": "Bica", "REBA": "Reba", "PIANO": "Piano",
    "UALA": "Uala", "BIBANK": "Bibank", "MARIVA": "Mariva",
    "DE CORRIENTES": "Corrientes", "DE FORMOSA": "Formosa",
    "DEL CHUBUT": "Chubut", "DINO": "Dino", "JULIO": "Julio",
    "MASVENTAS": "Masventas", "DE COMERCIO": "Comercio",
    "CRÉDITO REGIONAL": "Créd. Regional", "CREDITO REGIONAL": "Créd. Regional",
}

def abreviar(nombre: str) -> dict:
    if not nombre:
        return None
    u = nombre.upper().strip()
    for key, val in NOMBRE_CORTO.items():
        if key in u:
            return {"nombre": val, "mer": key == "MERIDIAN"}
    clean = u.replace("BANCO ", "").strip().split()[0].capitalize()
    return {"nombre": clean, "mer": False}

def limpiar_float(txt: str) -> float:
    """Convierte '1.410,0000' o '1,410.00' o '1410.00' a float."""
    if not txt:
        return None
    txt = txt.strip().replace("\xa0", "").replace(" ", "").replace("$", "")
    # Formato AR con 4 decimales: 1.410,0000
    if "," in txt and "." in txt:
        # Determinar cuál es separador de miles y cuál decimal
        last_dot = txt.rfind(".")
        last_comma = txt.rfind(",")
        if last_comma > last_dot:
            # Coma es decimal: 1.410,0000
            txt = txt.replace(".", "").replace(",", ".")
        else:
            # Punto es decimal: 1,410.00
            txt = txt.replace(",", "")
    elif "," in txt:
        txt = txt.replace(",", ".")
    txt = re.sub(r"[^\d.]", "", txt)
    try:
        v = float(txt)
        return v if v > 0 else None
    except Exception:
        return None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ════════════════════════════════════════════
# SCRAPERS — PLAZO FIJO
# ════════════════════════════════════════════

async def scrape_bcra_pf() -> list:
    """Playwright: abre BCRA plazos fijos online y extrae la tabla."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-extensions',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            '--disable-translate',
            '--hide-scrollbars',
            '--metrics-recording-only',
            '--mute-audio',
            '--no-first-run',
            '--safebrowsing-disable-auto-update',
            '--single-process',
        ])
        page = await browser.new_page()
        await page.set_extra_http_headers(HEADERS)
        await page.goto("https://www.bcra.gob.ar/plazos-fijos-online/",
                        wait_until="networkidle", timeout=30000)
        await asyncio.sleep(5)  # esperar carga JS

        # Usar BeautifulSoup sobre el HTML renderizado
        html = await page.content()
        await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        bancos = []

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            nombre_raw = cells[0].get_text().strip()
            if not nombre_raw or len(nombre_raw) < 3:
                continue
            if re.search(r'entidad|institución|banco\s*$', nombre_raw, re.I):
                continue

            mapped = abreviar(nombre_raw)
            if not mapped:
                continue

            def parse_tna(cell_idx):
                if len(cells) <= cell_idx:
                    return None
                txt = cells[cell_idx].get_text().strip().replace("%", "").replace(",", ".").strip()
                try:
                    val = float(txt)
                    return round(val, 2) if 5 < val < 150 else None
                except ValueError:
                    return None

            tna_no_clientes = parse_tna(3)  # columna no clientes
            tna_clientes    = parse_tna(2)  # columna clientes

            if tna_no_clientes:
                # Banco con tasa no-clientes → entra al ranking principal
                bancos.append({
                    "nombre": mapped["nombre"],
                    "tna30": tna_no_clientes,
                    "mer": mapped["mer"],
                    "es_no_cliente": True,
                })
            elif tna_clientes and "NACION" in nombre_raw.upper():
                # Nación solo tiene tasa clientes — incluir marcado
                bancos.append({
                    "nombre": mapped["nombre"],
                    "tna30": tna_clientes,
                    "mer": False,
                    "es_no_cliente": False,
                })

        seen = set()
        result = []
        for b in bancos:
            if b["nombre"] not in seen:
                seen.add(b["nombre"])
                result.append(b)
        result.sort(key=lambda x: x["tna30"], reverse=True)
        log.info(f"PF: {len(result)} bancos")
        return result

# ════════════════════════════════════════════
# SCRAPERS — DÓLAR BANCOS
# ════════════════════════════════════════════

def scrape_meridian() -> dict:
    """HTML estático — tabla de tipos de cambio Meridian."""
    try:
        r = requests.get("https://www.bancomeridian.com.ar/pizarra/",
                         headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 3 and "DÓLAR" in cells[0].get_text().upper():
                venta = limpiar_float(cells[2].get_text())
                # Filtrar: precio de cambio debe ser > 1000 (no confundir con tasas %)
                if venta and venta > 1000:
                    log.info(f"Meridian venta: {venta}")
                    return {"nombre": "Meridian", "venta": venta, "mer": True}
    except Exception as e:
        log.error(f"Meridian error: {e}")
    return None

async def scrape_plus() -> dict:
    """Playwright — página JS de Plus Cambio."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-extensions',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            '--disable-translate',
            '--hide-scrollbars',
            '--metrics-recording-only',
            '--mute-audio',
            '--no-first-run',
            '--safebrowsing-disable-auto-update',
            '--single-process',
        ])
            page = await browser.new_page()
            await page.set_extra_http_headers(HEADERS)
            await page.goto("https://www.plus.com.ar/cambio/home",
                            wait_until="networkidle", timeout=25000)
            try:
                await page.wait_for_selector("text=Dólar", timeout=10000)
            except Exception:
                pass
            content = await page.content()
            await browser.close()

        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text()
        # La página muestra: VENDÉS (compra del banco) luego COMPRÁS (venta del banco)
        # Tomamos el segundo número > 1000 que es el precio de venta
        matches = re.findall(r"(\d[\d.,]{3,})", text)
        precios = []
        for m in matches:
            v = limpiar_float(m)
            if v and 1000 < v < 3000:
                precios.append(v)
        if len(precios) >= 2:
            venta = precios[1]  # segundo precio = COMPRÁS = venta del banco
            log.info(f"Plus venta: {venta}")
            return {"nombre": "Plus Cambio", "venta": venta, "mer": False}
        elif len(precios) == 1:
            log.info(f"Plus venta (único): {precios[0]}")
            return {"nombre": "Plus Cambio", "venta": precios[0], "mer": False}
    except Exception as e:
        log.error(f"Plus error: {e}")
    return None

async def scrape_dolarito() -> list:
    """Playwright — dolarito.ar, solo Nación, BBVA e ICBC."""
    BANCOS_DOLARITO = {
        "banco nación": "Nación", "banco nacion": "Nación",
        "bbva banco francés": "BBVA", "bbva banco frances": "BBVA", "bbva": "BBVA",
        "icbc": "ICBC",
    }
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-extensions',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            '--disable-translate',
            '--hide-scrollbars',
            '--metrics-recording-only',
            '--mute-audio',
            '--no-first-run',
            '--safebrowsing-disable-auto-update',
            '--single-process',
        ])
            page = await browser.new_page()
            await page.set_extra_http_headers(HEADERS)
            await page.goto("https://www.dolarito.ar/cotizacion/bancos",
                            wait_until="networkidle", timeout=30000)
            await asyncio.sleep(4)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        matches = re.findall(
            r'La cotizaci[oó]n del d[oó]lar para la venta \(sin impuestos\) en (.+?) es \$([\d.]+)',
            text, re.IGNORECASE
        )

        bancos = []
        seen = set()
        for nombre_raw, precio_raw in matches:
            nombre_lower = nombre_raw.strip().lower()
            nombre = None
            for key, val in BANCOS_DOLARITO.items():
                if key in nombre_lower:
                    nombre = val
                    break
            if not nombre or nombre in seen:
                continue
            seen.add(nombre)
            venta = limpiar_float(precio_raw)
            if venta and venta > 1000:
                bancos.append({"nombre": nombre, "venta": venta, "mer": False})

        log.info(f"Dolarito: {len(bancos)} bancos")
        return bancos
    except Exception as e:
        log.error(f"Dolarito error: {e}")
        return []

async def scrape_dolar_bancos() -> list:
    """Meridian y Plus directo + Nación/BBVA/ICBC de dolarito."""
    loop = asyncio.get_event_loop()
    mer_res, plus_res = await asyncio.gather(
        loop.run_in_executor(None, scrape_meridian),
        scrape_plus(),
    )
    dolarito = await scrape_dolarito()

    seen = set()
    bancos = []
    for b in [mer_res, plus_res]:
        if b and b["nombre"] not in seen:
            seen.add(b["nombre"])
            bancos.append(b)
    for b in dolarito:
        if b["nombre"] not in seen:
            seen.add(b["nombre"])
            bancos.append(b)

    bancos.sort(key=lambda x: x["venta"])
    log.info(f"Dólar total: {len(bancos)} bancos")
    return bancos

# ════════════════════════════════════════════
# CACHE
# ════════════════════════════════════════════

cache = {
    "pf":    {"data": None, "ts": None, "error": None},
    "dolar": {"data": None, "ts": None, "error": None},
}

# ════════════════════════════════════════════
# TELEGRAM
# ════════════════════════════════════════════

# Configurar en archivo .env o como variables de entorno
from pathlib import Path
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

import os
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
REPORTE_HORA     = int(os.environ.get("REPORTE_HORA",   "9"))
REPORTE_MINUTO   = int(os.environ.get("REPORTE_MINUTO", "0"))

# Tasas previas para detectar cambios
tasas_previas = {}  # {nombre: tna30}

def telegram_enabled() -> bool:
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)

def enviar_telegram_foto(img_bytes: bytes):
    """Envía imagen PNG al grupo de Telegram via sendPhoto."""
    if not telegram_enabled():
        return
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        boundary = "----BoundaryMeridianPF"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{TELEGRAM_CHAT_ID}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="reporte.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        urllib.request.urlopen(req, timeout=30)
        log.info("✅ Telegram foto enviada")
    except Exception as e:
        log.error(f"❌ Telegram foto error: {e}")

def enviar_telegram(mensaje: str):
    """Envía mensaje de texto con Markdown."""
    if not telegram_enabled():
        return
    try:
        import urllib.request, json as _json
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = _json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        log.info("OK Telegram enviado")
    except Exception as e:
        log.error(f"Telegram error: {e}")

_logo_cache = None

def _get_logo():
    global _logo_cache
    if _logo_cache is not None:
        return _logo_cache
    try:
        from PIL import Image
        import numpy as np
        for name in ["logo.png", "preview.webp", "banco_meridian_sa_logo.jpg"]:
            logo_path = Path(__file__).parent / name
            if logo_path.exists():
                logo = Image.open(str(logo_path)).convert("RGBA")
                data = np.array(logo)
                r, g, b, a = data[:,:,0], data[:,:,1], data[:,:,2], data[:,:,3]
                mask = (r > 220) & (g > 220) & (b > 220)
                data[mask] = [255, 255, 255, 0]
                logo = Image.fromarray(data).resize((52, 52), Image.LANCZOS)
                _logo_cache = logo
                return logo
    except Exception as e:
        log.warning(f"Logo no disponible: {e}")
    return None

def generar_imagen_pf(bancos: list, cambios: list = None,
                      tasa_nacion_previa: float = None) -> bytes:
    """Genera la imagen PNG del reporte/alerta de tasas PF."""
    from PIL import Image, ImageDraw, ImageFont
    import io

    is_alert = bool(cambios)
    W, pad = 390, 16

    WHITE      = (255, 255, 255)
    BLUE_DARK  = (26,  86,  139)
    BLUE_LIGHT = (232, 240, 254)
    BLUE_TEXT  = (12,  56,  117)
    BLUE_SUB   = (74,  111, 165)
    GREEN_BOX  = (232, 248, 238)
    GREEN_DARK = (22,  101, 52)
    GREEN_MED  = (34,  133, 106)
    GRAY_BG    = (248, 248, 248)
    GRAY_LINE  = (238, 238, 238)
    GRAY_TEXT  = (153, 153, 153)
    BLACK      = (34,  34,  34)
    RED_BG     = (253, 232, 232)
    RED_TEXT   = (197, 48,  48)
    UP_GREEN   = (34,  197, 94)
    DN_RED     = (239, 68,  68)
    LINK_BLUE  = (26,  115, 232)

    def try_font(name, size):
        for d in ["C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu"]:
            try:
                return ImageFont.truetype(f"{d}/{name}", size)
            except:
                pass
        return ImageFont.load_default()

    fb   = try_font("DejaVuSans-Bold.ttf", 13)
    fb18 = try_font("DejaVuSans-Bold.ttf", 20)
    fb11 = try_font("DejaVuSans-Bold.ttf", 11)
    fb10 = try_font("DejaVuSans-Bold.ttf", 10)
    fr   = try_font("DejaVuSans.ttf",      12)
    fr11 = try_font("DejaVuSans.ttf",      11)
    fr10 = try_font("DejaVuSans.ttf",      10)

    bancos_no_nacion = [b for b in bancos if "naci" not in b["nombre"].lower()]
    nacion = next((b for b in bancos if "naci" in b["nombre"].lower()), None)

    mer, pos_mer  = calcular_pos_meridian(bancos_no_nacion)
    top5          = calcular_top5_dense(bancos_no_nacion)
    ranks         = dense_rank(bancos_no_nacion)
    total         = len(bancos_no_nacion)
    lider_tna     = bancos_no_nacion[0]["tna30"] if bancos_no_nacion else 0

    nacion_cambio = None
    if nacion and tasa_nacion_previa is not None and nacion["tna30"] != tasa_nacion_previa:
        nacion_cambio = nacion["tna30"] - tasa_nacion_previa

    n_movs = len(cambios) if cambios else 0
    if nacion_cambio is not None and is_alert:
        n_movs += 1
    H = (pad + 18 + 24 + 20 + 70 + 36 + 10
         + (16 + n_movs*17 + 14 if is_alert else 0)
         + 16 + len(top5)*17
         + 8 + 14 + pad + 10)

    img  = Image.new("RGBA", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    y    = pad

    draw.text((pad, y), "Monitoreo de Tasas Web", fill=LINK_BLUE, font=fb)
    logo = _get_logo()
    if logo:
        img.paste(logo, (W - pad - 52, y - 4), logo)
    y += 18

    badge_txt = "ALERTA DE CAMBIO" if is_alert else "REPORTE DIARIO"
    badge_bg  = RED_BG   if is_alert else BLUE_LIGHT
    badge_fg  = RED_TEXT if is_alert else BLUE_DARK
    bw = draw.textlength(badge_txt, font=fb10) + 18
    draw.rounded_rectangle([pad, y, pad+bw, y+18], radius=9, fill=badge_bg)
    draw.text((pad+9, y+3), badge_txt, fill=badge_fg, font=fb10)
    y += 24

    from datetime import datetime as _dt
    now = _dt.now()
    draw.text((pad, y), f"{now.strftime('%d/%m/%Y')} · {now.strftime('%H:%M')} AR",
              fill=(102,102,102), font=fr11)
    y += 20

    box_bg     = GREEN_BOX   if is_alert else BLUE_LIGHT
    box_border = (34,197,94) if is_alert else BLUE_DARK
    box_lbl    = GREEN_DARK  if is_alert else BLUE_DARK
    box_tna_c  = GREEN_DARK  if is_alert else BLUE_TEXT
    box_sub_c  = GREEN_MED   if is_alert else BLUE_SUB

    draw.rectangle([pad, y, W-pad, y+62], fill=box_bg)
    draw.rectangle([pad, y, pad+3, y+62], fill=box_border)
    draw.text((pad+10, y+6), "BANCO MERIDIAN", fill=box_lbl, font=fb10)
    if mer:
        tna_txt = f"{mer['tna30']:.2f}%"
        draw.text((pad+10, y+20), tna_txt, fill=box_tna_c, font=fb18)
        tw = draw.textlength(tna_txt, font=fb18)
        draw.text((pad+12+tw, y+26), "TNA no clientes", fill=box_sub_c, font=fr11)
        if is_alert:
            sub = f"#{pos_mer} de {total}"
        else:
            sub = f"#{pos_mer} de {total} · líder del mercado" if pos_mer == 1 else f"#{pos_mer} de {total}"
        draw.text((pad+10, y+46), sub, fill=box_sub_c, font=fr11)
    y += 70

    draw.rounded_rectangle([pad, y, W-pad, y+28], radius=6, fill=GRAY_BG, outline=GRAY_LINE)
    draw.text((pad+10, y+7), "Banco Nación  (clientes)", fill=(85,85,85), font=fr)
    if nacion:
        tasa_str = f"{nacion['tna30']:.2f}%"
        if is_alert and nacion_cambio is not None:
            var_str = f"{nacion_cambio:+.2f}%"
            tw_t = draw.textlength(tasa_str, font=fb)
            tw_v = draw.textlength(var_str, font=fb11)
            draw.text((W-pad-tw_v-tw_t-8, y+7), tasa_str, fill=BLACK, font=fb)
            draw.text((W-pad-tw_v, y+9), var_str,
                      fill=UP_GREEN if nacion_cambio > 0 else DN_RED, font=fb11)
        else:
            draw.text((W-pad-50, y+7), tasa_str, fill=BLACK, font=fb)
    y += 36

    draw.line([pad, y, W-pad, y], fill=GRAY_LINE)
    y += 10

    if is_alert and (cambios or nacion_cambio is not None):
        draw.text((pad, y), "MOVIMIENTOS DETECTADOS", fill=GRAY_TEXT, font=fb10)
        y += 16
        if nacion_cambio is not None and nacion:
            arrow = "▲" if nacion_cambio > 0 else "▼"
            col   = UP_GREEN if nacion_cambio > 0 else DN_RED
            tna_ant = nacion["tna30"] - nacion_cambio
            txt = f"{tna_ant:.2f} → {nacion['tna30']:.2f} ({nacion_cambio:+.2f}%)"
            draw.text((pad, y), arrow, fill=col, font=fb)
            draw.text((pad+14, y), "Nación", fill=BLACK, font=fb)
            bw2 = draw.textlength("Nación", font=fb)
            draw.text((pad+14+bw2+4, y), txt, fill=(85,85,85), font=fr)
            y += 17
        for banco_n, tna_ant, tna_new in (cambios or []):
            diff  = tna_new - tna_ant
            arrow = "▲" if diff > 0 else "▼"
            col   = UP_GREEN if diff > 0 else DN_RED
            txt   = f"{tna_ant:.2f} → {tna_new:.2f} ({diff:+.2f}%)"
            draw.text((pad, y), arrow, fill=col, font=fb)
            draw.text((pad+14, y), banco_n, fill=BLACK, font=fb)
            bw2 = draw.textlength(banco_n, font=fb)
            draw.text((pad+14+bw2+4, y), txt, fill=(85,85,85), font=fr)
            y += 17
        draw.line([pad, y+4, W-pad, y+4], fill=GRAY_LINE)
        y += 14

    draw.text((pad, y), "RANKING TOP 5", fill=GRAY_TEXT, font=fb10)
    y += 16
    for b in top5:
        pos    = ranks[b["tna30"]]
        star   = b["mer"]
        nombre = b["nombre"] + " ★" if star else b["nombre"]
        draw.text((pad, y), f"#{pos}", fill=GRAY_TEXT, font=fr10)
        draw.text((pad+26, y), nombre,
                  fill=BLUE_DARK if star else BLACK,
                  font=fb11 if star else fr)
        draw.text((W-pad-50, y), f"{b['tna30']:.2f}%", fill=BLACK, font=fb11)
        y += 17

    footer_y = H - pad - 14
    draw.line([pad, footer_y-8, W-pad, footer_y-8], fill=GRAY_LINE)
    draw.text((pad, footer_y), "bcra.gob.ar/plazos-fijos-online", fill=LINK_BLUE, font=fr11)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def calcular_top5_dense(bancos: list) -> list:
    """Devuelve los bancos del top 5 por dense rank."""
    if not bancos:
        return []
    tnas_sorted = sorted(set(b["tna30"] for b in bancos), reverse=True)
    top5_tnas = set(tnas_sorted[:5])
    return [b for b in bancos if b["tna30"] in top5_tnas]

def calcular_pos_meridian(bancos: list) -> tuple:
    """Dense rank de Meridian. Retorna (banco, posicion)."""
    mer = next((b for b in bancos if b["mer"]), None)
    if not mer:
        return None, None
    tnas_superiores = set(b["tna30"] for b in bancos if b["tna30"] > mer["tna30"])
    return mer, len(tnas_superiores) + 1

def dense_rank(bancos: list) -> dict:
    tnas_sorted = sorted(set(b["tna30"] for b in bancos), reverse=True)
    return {tna: i+1 for i, tna in enumerate(tnas_sorted)}

def formatear_reporte(bancos: list, cambios: list = None,
                      tasa_nacion_previa: float = None) -> str:
    from datetime import datetime as dt
    now   = dt.now()
    fecha = now.strftime("%d/%m/%Y")
    hora  = now.strftime("%H:%M")

    bancos_no_nacion = [b for b in bancos if "naci" not in b["nombre"].lower()]
    nacion           = next((b for b in bancos if "naci" in b["nombre"].lower()), None)

    mer, pos_mer = calcular_pos_meridian(bancos_no_nacion)
    top5         = calcular_top5_dense(bancos_no_nacion)
    ranks        = dense_rank(bancos_no_nacion)
    total        = len(bancos_no_nacion)

    is_alert = bool(cambios or tasa_nacion_previa)
    icono    = "🔔" if is_alert else "📋"
    tipo     = "ALERTA DE CAMBIO" if is_alert else "REPORTE DIARIO"

    lines = [
        f"*{icono} {tipo}*",
        f"_{fecha} · {hora} AR_",
        "",
        "*🔷 BANCO MERIDIAN*",
    ]

    if mer:
        lider_txt = "lider del mercado" if pos_mer == 1 else f"gap {mer['tna30'] - bancos_no_nacion[0]['tna30']:+.2f}%"
        lines += [
            f"`  {mer['tna30']:.2f}%  TNA no clientes`",
            f"`  #{pos_mer} de {total} · {lider_txt}`",
        ]
    lines.append("")

    if nacion:
        nacion_cambio = None
        if tasa_nacion_previa is not None and nacion["tna30"] != tasa_nacion_previa:
            nacion_cambio = nacion["tna30"] - tasa_nacion_previa
        if nacion_cambio is not None:
            signo = f"+{nacion_cambio:.2f}%" if nacion_cambio > 0 else f"{nacion_cambio:.2f}%"
            lines.append(f"*🏛* `Nacion (clientes)   {nacion['tna30']:>6.2f}%  {signo}`")
        else:
            lines.append(f"*🏛* `Nacion (clientes)   {nacion['tna30']:>6.2f}%`")

    lines.append("")

    if is_alert and (cambios or tasa_nacion_previa is not None):
        lines.append("*⚠️ Movimientos detectados*")
        if tasa_nacion_previa is not None and nacion:
            nacion_cambio = nacion["tna30"] - tasa_nacion_previa
            arrow = "▲" if nacion_cambio > 0 else "▼"
            lines.append(f"`{arrow} Nacion        {tasa_nacion_previa:.2f} → {nacion['tna30']:.2f} ({nacion_cambio:+.2f}%)`")
        for banco_n, tna_ant, tna_new in (cambios or []):
            diff  = tna_new - tna_ant
            arrow = "▲" if diff > 0 else "▼"
            lines.append(f"`{arrow} {banco_n:<13} {tna_ant:.2f} → {tna_new:.2f} ({diff:+.2f}%)`")
        lines.append("")

    lines.append("*📊 Ranking top 5*")
    for b in top5:
        pos    = ranks[b["tna30"]]
        marker = " <<" if b["mer"] else "   "
        lines.append(f"`#{pos}  {b['nombre']:<16} {b['tna30']:>6.2f}%{marker}`")

    lines += [
        "",
        "`bcra.gob.ar/plazos-fijos-online`",
    ]
    return "\n".join(lines)


def detectar_cambios(bancos_nuevos: list) -> tuple:
    """Compara tasas nuevas vs previas.
    Retorna (cambios, tasa_nacion_previa).
    cambios: lista de (nombre, tna_ant, tna_new) — excluye Nacion.
    tasa_nacion_previa: float si Nacion cambio, None si no.
    """
    global tasas_previas
    cambios = []
    tasa_nacion_previa = None

    bancos_no_nacion = [b for b in bancos_nuevos if "naci" not in b["nombre"].lower()]
    nacion = next((b for b in bancos_nuevos if "naci" in b["nombre"].lower()), None)

    top5 = calcular_top5_dense(bancos_no_nacion)
    monitoreados = {b["nombre"] for b in top5}
    monitoreados.update(b["nombre"] for b in bancos_no_nacion if b["mer"])

    for banco in bancos_no_nacion:
        if banco["nombre"] not in monitoreados:
            continue
        tna_nueva  = banco["tna30"]
        tna_previa = tasas_previas.get(banco["nombre"])
        if tna_previa is not None and tna_nueva != tna_previa:
            cambios.append((banco["nombre"], tna_previa, tna_nueva))

    if nacion:
        tna_previa_nac = tasas_previas.get(nacion["nombre"])
        if tna_previa_nac is not None and nacion["tna30"] != tna_previa_nac:
            tasa_nacion_previa = tna_previa_nac

    tasas_previas = {b["nombre"]: b["tna30"] for b in bancos_nuevos}
    return cambios, tasa_nacion_previa

# ════════════════════════════════════════════
# LOOPS DE REFRESCO
# ════════════════════════════════════════════

async def refresh_pf():
    primer_ciclo = True
    while True:
        if not es_horario_habil():
            log.info("PF: fuera de horario hábil — esperando...")
            await asyncio.sleep(60)
            continue
        try:
            log.info("Actualizando PF...")
            data = await scrape_bcra_pf()
            if data:
                cache["pf"]["data"]  = data
                cache["pf"]["ts"]    = datetime.now().isoformat()
                cache["pf"]["error"] = None
                log.info(f"✅ PF: {len(data)} bancos")

                if primer_ciclo:
                    tasas_previas.update({b["nombre"]: b["tna30"] for b in data})
                    primer_ciclo = False
                else:
                    cambios, tna_nac_prev = detectar_cambios(data)
                    if (cambios or tna_nac_prev is not None) and telegram_enabled():
                        log.info(f"Cambios detectados: {len(cambios)}")
                        msg = formatear_reporte(data, cambios, tna_nac_prev)
                        enviar_telegram(msg)
            else:
                cache["pf"]["error"] = "Sin datos"
        except Exception as e:
            cache["pf"]["error"] = str(e)
            log.error(f"❌ PF error: {e}")
        await asyncio.sleep(PF_REFRESH_SECONDS)

async def reporte_diario():
    """Envía reporte fijo todos los días a REPORTE_HORA (hora Argentina)."""
    from datetime import datetime as dt
    while True:
        now = dt.now()
        # Calcular segundos hasta próximas REPORTE_HORA:00 AR
        target = now.replace(hour=REPORTE_HORA, minute=REPORTE_MINUTO, second=0, microsecond=0)
        if now >= target:
            # Ya pasó hoy — esperar hasta mañana
            from datetime import timedelta
            target += timedelta(days=1)
        espera = (target - now).total_seconds()
        log.info(f"Próximo reporte diario en {espera/3600:.1f}h ({target.strftime('%d/%m %H:%M')})")
        await asyncio.sleep(espera)

        if cache["pf"]["data"] and telegram_enabled():
            log.info("Enviando reporte diario Telegram...")
            msg = formatear_reporte(cache["pf"]["data"])
            enviar_telegram(msg)

async def refresh_dolar():
    while True:
        if not es_horario_habil():
            await asyncio.sleep(60)
            continue
        try:
            log.info("Actualizando Dólar...")
            data = await scrape_dolar_bancos()
            if data:
                cache["dolar"]["data"]  = data
                cache["dolar"]["ts"]    = datetime.now().isoformat()
                cache["dolar"]["error"] = None
                log.info(f"✅ Dólar: {len(data)} bancos")
            else:
                cache["dolar"]["error"] = "Sin datos"
        except Exception as e:
            cache["dolar"]["error"] = str(e)
            log.error(f"❌ Dólar error: {e}")
        await asyncio.sleep(DOLAR_REFRESH_SECONDS)

# ════════════════════════════════════════════
# STARTUP
# ════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    asyncio.create_task(refresh_pf())
    asyncio.create_task(refresh_dolar())
    if telegram_enabled():
        asyncio.create_task(reporte_diario())
        log.info(f"✅ Telegram habilitado — reporte diario a las {REPORTE_HORA}:{REPORTE_MINUTO:02d} AR")
    else:
        log.info("⚠️  Telegram no configurado — crear .env con TELEGRAM_TOKEN y TELEGRAM_CHAT_ID")
    if telegram_enabled():
        asyncio.create_task(iamc_loop())
        log.info("✅ IAMC loop iniciado — primer intento a las 17:15 AR")

# ════════════════════════════════════════════
# IAMC — DESCARGA Y GENERACIÓN DE INFORME
# ════════════════════════════════════════════

IAMC_HORA_INICIO  = 17
IAMC_MIN_INICIO   = 15
IAMC_RETRY_MIN    = 5
LOGO_PATH         = Path(__file__).parent / "logo.png"
GENERATOR_PATH    = Path(__file__).parent / "generate_report_v3.py"
DIR_DESCARGAS     = Path(__file__).parent / "descargas"
DIR_INFORMES      = Path(__file__).parent / "informes"
DIR_FLAGS         = Path(__file__).parent / "logs"

HEADERS_IAMC = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
}

def iamc_ya_procesado(fecha: "date") -> bool:
    DIR_FLAGS.mkdir(parents=True, exist_ok=True)
    return (DIR_FLAGS / f"iamc_done_{fecha.strftime('%Y%m%d')}.flag").exists()

def iamc_marcar_procesado(fecha: "date"):
    DIR_FLAGS.mkdir(parents=True, exist_ok=True)
    (DIR_FLAGS / f"iamc_done_{fecha.strftime('%Y%m%d')}.flag").touch()

def iamc_urls(fecha: "date") -> dict:
    f = fecha.strftime("%d%m%Y")
    return {
        "renta_fija": f"https://www.iamc.com.ar/Informe/InformeRentaFija{f}/",
        "tesoro":     f"https://www.iamc.com.ar/Informe/InformeLetrasyBonosdelTesoroyCaucion{f}/",
    }

async def iamc_descargar_pdf(url: str, destino: Path) -> bool:
    """Descarga el PDF del IAMC interceptando la URL temporal generada por el visor."""
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        pdf_url = None
        pdf_bytes = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-extensions',
            '--disable-background-networking',
            '--mute-audio',
            '--no-first-run',
            '--single-process',
        ])
            context = await browser.new_context(
                accept_downloads=True,
                extra_http_headers=HEADERS_IAMC,
            )
            page = await context.new_page()

            # Interceptar respuestas PDF
            async def on_response(response):
                nonlocal pdf_url, pdf_bytes
                ct = response.headers.get("content-type", "")
                if "application/pdf" in ct and pdf_url is None:
                    pdf_url = response.url
                    log.info(f"IAMC: PDF interceptado en {pdf_url}")
                    try:
                        pdf_bytes = await response.body()
                    except Exception:
                        pass

            page.on("response", on_response)

            log.info(f"IAMC: abriendo {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(8)  # esperar que cargue el visor y el PDF

            await browser.close()

        # Guardar PDF si fue interceptado
        if pdf_bytes and len(pdf_bytes) > 1000:
            destino.write_bytes(pdf_bytes)
            log.info(f"IAMC: ✅ {destino.name} ({len(pdf_bytes)//1024} KB)")
            return True

        # Fallback: descargar desde la URL temporal si la tenemos
        if pdf_url:
            import urllib.request, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(pdf_url, headers=HEADERS_IAMC)
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                content = resp.read()
            if content[:4] == b"%PDF":
                destino.write_bytes(content)
                log.info(f"IAMC: ✅ {destino.name} (fallback URL, {len(content)//1024} KB)")
                return True

        log.warning(f"IAMC: no se encontró PDF en {url}")
        return False

    except Exception as e:
        log.error(f"IAMC: error descargando {url}: {e}")
        return False

def enviar_telegram_documento(path_pdf: Path) -> bool:
    """Envía el PDF al grupo de Telegram via sendDocument."""
    if not telegram_enabled():
        return False
    try:
        import urllib.request, urllib.parse
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"

        boundary = "----BoundaryMeridian"
        pdf_bytes = path_pdf.read_bytes()
        filename  = path_pdf.name

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{TELEGRAM_CHAT_ID}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode() + pdf_bytes + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        urllib.request.urlopen(req, timeout=60)
        log.info(f"✅ PDF enviado a Telegram: {filename}")
        return True
    except Exception as e:
        log.error(f"❌ Error enviando PDF Telegram: {e}")
        return False

async def iamc_procesar(fecha: "date") -> bool:
    """Descarga, genera y envía el informe IAMC del día."""
    import sys
    if iamc_ya_procesado(fecha):
        log.info(f"IAMC: ya procesado {fecha.strftime('%d/%m/%Y')}")
        return True

    urls = iamc_urls(fecha)
    dir_fecha   = DIR_DESCARGAS / fecha.strftime("%Y%m%d")
    path_renta  = dir_fecha / f"renta_fija_{fecha.strftime('%Y%m%d')}.pdf"
    path_tesoro = dir_fecha / f"tesoro_{fecha.strftime('%Y%m%d')}.pdf"

    log.info(f"IAMC: verificando informes para {fecha.strftime('%d/%m/%Y')}...")

    # Descargar ambos PDFs
    ok_renta  = await iamc_descargar_pdf(urls["renta_fija"], path_renta)
    ok_tesoro = await iamc_descargar_pdf(urls["tesoro"],     path_tesoro)

    if not ok_renta or not ok_tesoro:
        log.info("IAMC: informes aún no disponibles")
        return False

    # Generar informe corporativo
    DIR_INFORMES.mkdir(parents=True, exist_ok=True)
    path_salida = DIR_INFORMES / f"BM_Mercado_{fecha.strftime('%Y%m%d')}.pdf"

    if not GENERATOR_PATH.exists():
        log.error(f"IAMC: generador no encontrado: {GENERATOR_PATH}")
        return False

    import subprocess
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH),
         "--fecha",  fecha.strftime("%d%m%Y"),
         "--renta",  str(path_renta),
         "--tesoro", str(path_tesoro),
         "--salida", str(path_salida),
         "--logo",   str(LOGO_PATH)],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        log.error(f"IAMC: error generando PDF: {result.stderr}")
        return False

    log.info(f"IAMC: ✅ PDF generado {path_salida.name}")

    # Enviar por Telegram
    if telegram_enabled():
        enviar_telegram_documento(path_salida)

    iamc_marcar_procesado(fecha)
    return True

async def iamc_loop():
    """Loop principal IAMC: espera las 17:15, reintenta cada 5 min."""
    from datetime import date as date_type, timedelta
    while True:
        now    = datetime.now()
        fecha  = now.date()

        # Solo días hábiles (lunes=0 ... viernes=4)
        if now.weekday() >= 5:
            # Esperar hasta el lunes
            dias = 7 - now.weekday()
            log.info(f"IAMC: fin de semana — próximo intento en {dias} días")
            await asyncio.sleep(dias * 86400)
            continue

        # Calcular próximo intento de hoy: 17:15 o siguiente múltiplo de 5 min
        target = now.replace(hour=IAMC_HORA_INICIO, minute=IAMC_MIN_INICIO, second=0, microsecond=0)
        if now < target:
            espera = (target - now).total_seconds()
            log.info(f"IAMC: esperando hasta las {IAMC_HORA_INICIO}:{IAMC_MIN_INICIO:02d} ({espera/60:.0f} min)")
            await asyncio.sleep(espera)
            continue

        # Hora de intentar
        if not iamc_ya_procesado(fecha):
            ok = await iamc_procesar(fecha)
            if ok:
                # Procesado exitosamente — dormir hasta mañana a las 17:15
                manana = datetime.now().replace(hour=IAMC_HORA_INICIO, minute=IAMC_MIN_INICIO, second=0) + timedelta(days=1)
                espera = (manana - datetime.now()).total_seconds()
                log.info(f"IAMC: ✅ Completado — próximo ciclo en {espera/3600:.1f}h")
                await asyncio.sleep(espera)
            else:
                # Reintentar en IAMC_RETRY_MIN minutos
                log.info(f"IAMC: reintentando en {IAMC_RETRY_MIN} min")
                await asyncio.sleep(IAMC_RETRY_MIN * 60)
        else:
            # Ya procesado hoy — dormir hasta mañana
            manana = datetime.now().replace(hour=IAMC_HORA_INICIO, minute=IAMC_MIN_INICIO, second=0) + timedelta(days=1)
            espera = (manana - datetime.now()).total_seconds()
            await asyncio.sleep(espera)

# ════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════

@app.get("/pf")
async def get_pf():
    if cache["pf"]["data"]:
        return {"ok": True, "source": "local-bcra", "data": cache["pf"]["data"], "ts": cache["pf"]["ts"], "horario_habil": es_horario_habil()}
    return {"ok": False, "error": cache["pf"]["error"] or "Esperando primer scraping...", "horario_habil": es_horario_habil()}

@app.get("/dolar")
async def get_dolar():
    if cache["dolar"]["data"]:
        return {"ok": True, "source": "local-scraping", "data": cache["dolar"]["data"], "ts": cache["dolar"]["ts"], "horario_habil": es_horario_habil()}
    return {"ok": False, "error": cache["dolar"]["error"] or "Esperando primer scraping...", "horario_habil": es_horario_habil()}

@app.get("/health")
async def health():
    return {
        "ok": True,
        "ts": datetime.now().isoformat(),
        "pf": {
            "bancos": len(cache["pf"]["data"]) if cache["pf"]["data"] else 0,
            "ultima_actualizacion": cache["pf"]["ts"],
            "error": cache["pf"]["error"],
        },
        "dolar": {
            "bancos": len(cache["dolar"]["data"]) if cache["dolar"]["data"] else 0,
            "ultima_actualizacion": cache["dolar"]["ts"],
            "error": cache["dolar"]["error"],
        },
    }

# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  Dashboard Mercados — Servidor Local")
    print("=" * 60)
    print(f"  Puerto   : {PORT}")
    print(f"  Refresco : cada {REFRESH_SECONDS}s")
    print()
    print("  Endpoints:")
    print(f"    http://localhost:{PORT}/health")
    print(f"    http://localhost:{PORT}/pf")
    print(f"    http://localhost:{PORT}/dolar")
    print()
    print("  Cloudflare Tunnel:")
    print("    cloudflared.exe tunnel --url http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
