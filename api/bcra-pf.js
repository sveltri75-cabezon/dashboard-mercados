// Vercel Serverless Function — scraping plazo fijo BCRA
// Parsea la tabla de https://www.bcra.gob.ar/plazos-fijos-online/
// usando fetch + regex (sin Puppeteer para tier gratuito)

const BCRA_URL = 'https://www.bcra.gob.ar/plazos-fijos-online/';

// Mapeo de nombre largo → nombre corto
const NOMBRE_CORTO = {
  'BANCO DE GALICIA Y BUENOS AIRES S.A.U.': 'Galicia',
  'BANCO DE LA NACION ARGENTINA': 'Nación',
  'BANCO DE LA PROVINCIA DE BUENOS AIRES': 'Provincia',
  'BANCO BBVA ARGENTINA S.A.': 'BBVA',
  'BANCO SANTANDER ARGENTINA S.A.': 'Santander',
  'BANCO MACRO S.A.': 'Macro',
  'BANCO CIUDAD DE BUENOS AIRES': 'Ciudad',
  'BANCO HIPOTECARIO S.A.': 'Hipotecario',
  'HSBC BANK ARGENTINA S.A.': 'HSBC',
  'ICBC (INDUSTRIAL AND COMMERCIAL BANK OF CHINA)': 'ICBC',
  'BANCO MERIDIAN S.A.': 'Meridian',
  'PLUS INVERSIONES S.A.': 'Plus Cambio',
};

function abreviar(nombre) {
  const upper = nombre.toUpperCase().trim();
  for (const [key, val] of Object.entries(NOMBRE_CORTO)) {
    if (upper.includes(key.replace(/S\.A\.U?\.?/g, '').trim())) return val;
  }
  // fallback: primera palabra significativa
  return nombre.split(' ').filter(w => w.length > 3)[0] || nombre.slice(0, 12);
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');

  try {
    const r = await fetch(BCRA_URL, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'es-AR,es;q=0.9',
      }
    });

    if (!r.ok) throw new Error(`BCRA HTTP ${r.status}`);
    const html = await r.text();

    // Extraer filas de la tabla
    const rowRegex = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
    const cellRegex = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi;
    const stripTags = s => s.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim();

    const bancos = [];
    let match;
    while ((match = rowRegex.exec(html)) !== null) {
      const row = match[1];
      const cells = [];
      let cm;
      const cellCopy = new RegExp(cellRegex.source, 'gi');
      while ((cm = cellCopy.exec(row)) !== null) {
        cells.push(stripTags(cm[1]));
      }
      if (cells.length >= 3) {
        const nombre = cells[0];
        const tna30  = parseFloat(cells[1]?.replace(',', '.')) || null;
        const tna60  = parseFloat(cells[2]?.replace(',', '.')) || null;
        if (nombre && tna30 && nombre.length > 3 && !nombre.toLowerCase().includes('entidad')) {
          bancos.push({
            nombre: abreviar(nombre),
            nombreCompleto: nombre,
            tna30,
            tna60,
            mer: nombre.toUpperCase().includes('MERIDIAN'),
          });
        }
      }
    }

    if (!bancos.length) throw new Error('No se parsearon datos de la tabla BCRA');

    // Ordenar por TNA30 desc
    bancos.sort((a, b) => b.tna30 - a.tna30);

    res.status(200).json({ ok: true, data: bancos, ts: new Date().toISOString() });

  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
}
