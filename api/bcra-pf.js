// api/bcra-pf.js — proxy al servidor Cloud Run
const LOCAL_SERVER = process.env.LOCAL_SERVER_URL || 'https://cabezon-server-342455707797.us-central1.run.app';

const NOMBRE_CORTO = {
  'NACION': 'Nación', 'GALICIA': 'Galicia', 'PROVINCIA DE BUENOS': 'Provincia BsAs',
  'PROVINCIA DE CORDOBA': 'Prov. Córdoba', 'PROVINCIA DE TIERRA': 'Prov. T. del Fuego',
  'PROVINCIA': 'Provincia', 'BBVA': 'BBVA', 'SANTANDER': 'Santander',
  'MACRO': 'Macro', 'CIUDAD': 'Ciudad', 'HIPOTECARIO': 'Hipotecario',
  'MERIDIAN': 'Meridian', 'VOII': 'VOII', 'DEL SOL': 'Banco del Sol',
  'CMF': 'CMF', 'BICA': 'Bica', 'REBA': 'Reba', 'MASVENTAS': 'Masventas',
  'CRÉDITO REGIONAL': 'Créd. Regional', 'CREDITO REGIONAL': 'Créd. Regional',
  'BIBANK': 'Bibank', 'MARIVA': 'Mariva', 'DINO': 'Dino', 'JULIO': 'Julio',
  'COMAFI': 'Comafi', 'CREDICOOP': 'Credicoop', 'UALA': 'Uala',
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

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=120');

  // 1. Intentar servidor Cloud Run (Playwright propio)
  try {
    const r = await fetch(`${LOCAL_SERVER}/pf`, {
      headers: { 'User-Agent': 'Mozilla/5.0' },
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) throw new Error(`Server HTTP ${r.status}`);
    const data = await r.json();
    if (data.ok && data.data?.length) {
      return res.status(200).json({
        ok: true,
        source: 'local-python',
        data: data.data,
        ts: data.ts,
      });
    }
    throw new Error(data.error || 'Sin datos del servidor');
  } catch (e) {
    // 2. Fallback: ArgentinaDatos
    try {
      const r2 = await fetch('https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo/');
      const data = await r2.json();
      if (Array.isArray(data) && data.length) {
        const bancos = data
          .map(b => {
            const tnaRaw = b.tnaNoClientes ?? b.tnaClientes ?? 0;
            const tna30 = tnaRaw > 1 ? +parseFloat(tnaRaw).toFixed(2) : +parseFloat(tnaRaw * 100).toFixed(2);
            const mapped = abreviar(b.entidad);
            return {
              nombre: mapped?.nombre || b.entidad,
              tna30,
              mer: /meridian/i.test(b.entidad),
            };
          })
          .filter(b => b.tna30 > 0)
          .sort((a, b) => b.tna30 - a.tna30);
        return res.status(200).json({
          ok: true,
          source: 'argentinadatos-fallback',
          data: bancos,
          ts: new Date().toISOString(),
        });
      }
    } catch {}

    return res.status(500).json({ ok: false, error: e.message });
  }
}
