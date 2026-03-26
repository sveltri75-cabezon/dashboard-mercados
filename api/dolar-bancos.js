// api/dolar-bancos.js
// Combina DolarBot API (bancos principales) + scraping Puppeteer (Meridian, Plus Cambio)

const DOLARBOT_BANKS = [
  { key: 'nacion',    nombre: 'Nación' },
  { key: 'bbva',      nombre: 'BBVA' },
  { key: 'piano',     nombre: 'Piano' },
  { key: 'hipotecario', nombre: 'Hipotecario' },
  { key: 'galicia',   nombre: 'Galicia' },
  { key: 'santander', nombre: 'Santander' },
  { key: 'ciudad',    nombre: 'Ciudad' },
  { key: 'supervielle', nombre: 'Supervielle' },
  { key: 'patagonia', nombre: 'Patagonia' },
  { key: 'comafi',    nombre: 'Comafi' },
  { key: 'bind',      nombre: 'BIND' },
  { key: 'icbc',      nombre: 'ICBC' },
];

async function fetchDolarBot(key) {
  try {
    const r = await fetch(`https://api.dolarbot.io/api/dolar/bancos/${key}`, {
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    if (!r.ok) return null;
    const d = await r.json();
    return parseFloat(d?.venta) || null;
  } catch { return null; }
}

async function scrapeMeridian() {
  try {
    // Meridian publica su cotización en su home
    const r = await fetch('https://www.bancoMeridian.com.ar/', {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
    });
    if (!r.ok) return null;
    const html = await r.text();
    // Buscar patrón de cotización dólar venta
    const match = html.match(/d[oó]lar[^$]*\$\s*([\d.,]+)/i) ||
                  html.match(/venta[^$]*\$\s*([\d.,]+)/i) ||
                  html.match(/USD[^$]*\$\s*([\d.,]+)/i);
    if (match) return parseFloat(match[1].replace('.','').replace(',','.'));
    return null;
  } catch { return null; }
}

async function scrapePlus() {
  try {
    const r = await fetch('https://www.pluscambio.com.ar/', {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
    });
    if (!r.ok) return null;
    const html = await r.text();
    const match = html.match(/d[oó]lar[^$]*\$\s*([\d.,]+)/i) ||
                  html.match(/venta[^$]*\$\s*([\d.,]+)/i);
    if (match) return parseFloat(match[1].replace('.','').replace(',','.'));
    return null;
  } catch { return null; }
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=30, stale-while-revalidate=60');

  // Fetch all DolarBot banks in parallel
  const dolarBotResults = await Promise.all(
    DOLARBOT_BANKS.map(async b => {
      const venta = await fetchDolarBot(b.key);
      return venta ? { nombre: b.nombre, venta, mer: false } : null;
    })
  );

  // Scrape Meridian and Plus in parallel
  const [meridianVenta, plusVenta] = await Promise.all([
    scrapeMeridian(),
    scrapePlus(),
  ]);

  const bancos = dolarBotResults.filter(Boolean);

  if (meridianVenta) bancos.push({ nombre: 'Meridian', venta: meridianVenta, mer: true });
  if (plusVenta)     bancos.push({ nombre: 'Plus Cambio', venta: plusVenta, mer: false });

  if (!bancos.length) {
    return res.status(500).json({ ok: false, error: 'No se obtuvieron cotizaciones' });
  }

  // Sort by venta asc (más barato primero)
  bancos.sort((a, b) => a.venta - b.venta);

  res.status(200).json({ ok: true, data: bancos, ts: new Date().toISOString() });
}
