// api/bcra-pf.js
// Usa Browserless.io para renderizar la página del BCRA con JS completo

const BROWSERLESS_TOKEN = process.env.BROWSERLESS_TOKEN || '2UFePR4CoB5pVQx595f1788ea888c987e3807f0611346a48e';
const BCRA_URL = 'https://www.bcra.gob.ar/plazos-fijos-online/';

const NOMBRE_CORTO = {
  'NACION': 'Nación', 'GALICIA': 'Galicia', 'PROVINCIA': 'Provincia',
  'BBVA': 'BBVA', 'SANTANDER': 'Santander', 'MACRO': 'Macro',
  'CIUDAD': 'Ciudad', 'HIPOTECARIO': 'Hipotecario', 'HSBC': 'HSBC',
  'ICBC': 'ICBC', 'MERIDIAN': 'Meridian', 'PLUS': 'Plus Cambio',
  'BRUBANK': 'Brubank', 'PATAGONIA': 'Patagonia', 'SUPERVIELLE': 'Supervielle',
  'CREDICOOP': 'Credicoop', 'COMAFI': 'Comafi', 'BIND': 'BIND',
  'NARANJA': 'Naranja X', 'VOII': 'VOII', 'SOL': 'Banco del Sol',
  'CMF': 'CMF', 'BICA': 'Bica', 'REBA': 'Reba', 'PIANO': 'Piano',
};

function abreviar(nombre) {
  if (!nombre) return null;
  const u = nombre.toUpperCase().trim();
  for (const [key, val] of Object.entries(NOMBRE_CORTO)) {
    if (u.includes(key)) return { nombre: val, mer: key === 'MERIDIAN' };
  }
  const clean = nombre.replace(/BANCO\s+/i, '').trim().split(/\s+/)[0];
  return { nombre: clean, mer: false };
}

function stripTags(str) {
  return str.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').trim();
}

function parsearHTML(html) {
  const rows = html.match(/<tr[^>]*>[\s\S]*?<\/tr>/gi) || [];
  const bancos = [];

  for (const row of rows) {
    const cells = (row.match(/<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi) || [])
      .map(c => stripTags(c));

    if (cells.length < 2) continue;
    const nombre = cells[0];
    if (!nombre || nombre.length < 3) continue;
    if (/entidad|institución|banco\s*$/i.test(nombre)) continue;

    let tna = null;
    for (let i = 1; i < cells.length; i++) {
      const val = parseFloat(cells[i].replace(',', '.'));
      if (!isNaN(val) && val > 5 && val < 150) { tna = val; break; }
    }
    if (!tna) continue;

    const mapped = abreviar(nombre);
    if (!mapped) continue;
    bancos.push({ nombre: mapped.nombre, tna30: tna, mer: mapped.mer });
  }

  return bancos;
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=120, stale-while-revalidate=300');

  try {
    // Browserless content API — renderiza la página con JS y devuelve el HTML
    const r = await fetch(`https://chrome.browserless.io/content?token=${BROWSERLESS_TOKEN}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: BCRA_URL,
        waitFor: 3000, // esperar 3s a que cargue el JS
        gotoOptions: { waitUntil: 'networkidle2', timeout: 15000 },
      }),
    });

    if (!r.ok) throw new Error(`Browserless HTTP ${r.status}: ${await r.text()}`);
    const html = await r.text();

    const bancos = parsearHTML(html);
    if (!bancos.length) throw new Error(`Sin datos en HTML (${html.length} chars)`);

    const seen = new Set();
    const result = bancos
      .filter(b => { if (seen.has(b.nombre)) return false; seen.add(b.nombre); return true; })
      .sort((a, b) => b.tna30 - a.tna30);

    return res.status(200).json({ ok: true, source: 'bcra-browserless', data: result, ts: new Date().toISOString() });

  } catch (e) {
    // Fallback: ArgentinaDatos
    try {
      const r2 = await fetch('https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo/');
      const data = await r2.json();
      if (Array.isArray(data) && data.length) {
        const bancos = data
          .map(b => {
            const tnaRaw = b.tnaNoClientes ?? b.tnaClientes ?? 0;
            const tna30 = tnaRaw > 1 ? +parseFloat(tnaRaw).toFixed(2) : +parseFloat(tnaRaw * 100).toFixed(2);
            const mapped = abreviar(b.entidad);
            return { nombre: mapped?.nombre || b.entidad, tna30, mer: /meridian/i.test(b.entidad) };
          })
          .filter(b => b.tna30 > 0)
          .sort((a, b) => b.tna30 - a.tna30);
        return res.status(200).json({ ok: true, source: 'argentinadatos-fallback', data: bancos, ts: new Date().toISOString() });
      }
    } catch {}

    return res.status(500).json({ ok: false, error: e.message });
  }
}
