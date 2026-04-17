// Proxy BCRA TAMAR — variable 44
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store');
  try {
    const r = await fetch('https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/44', {
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    const data = await r.json();
    // Asegurar orden ascendente por fecha
    if (data?.results?.[0]?.detalle) {
      data.results[0].detalle.sort((a, b) => a.fecha.localeCompare(b.fecha));
    }
    res.status(200).json(data);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
