// api/historico.js
// Trae histórico de bonos desde data912 para calcular MEP/CCL de 30 días
// GET /api/historico?ticker=AL30   → array [{fecha, cierre}]

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=7200');

  const { ticker } = req.query;
  if (!ticker) return res.status(400).json({ error: 'ticker requerido' });

  try {
    const r = await fetch(`https://data912.com/historical/bonds/${ticker.toUpperCase()}`, {
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    if (!r.ok) throw new Error(`data912 HTTP ${r.status}`);
    const data = await r.json();

    // Normalizar al formato [{fecha, cierre}] y tomar últimos 30 días
    const normalizado = (Array.isArray(data) ? data : data.data || data.results || [])
      .map(d => ({
        fecha:  d.date || d.fecha || d.d,
        cierre: parseFloat(d.close || d.cierre || d.c) || null,
      }))
      .filter(d => d.fecha && d.cierre)
      .slice(-30);

    res.status(200).json({ ok: true, ticker: ticker.toUpperCase(), data: normalizado });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
}
