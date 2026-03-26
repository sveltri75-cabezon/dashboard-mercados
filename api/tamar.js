// Proxy BCRA TAMAR — variable 44
// BCRA tiene CORS abierto pero por si acá en producción hay issues
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=7200');
  try {
    const r = await fetch('https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/44', {
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    const data = await r.json();
    res.status(200).json(data);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
