// api/dolar-bancos.js — proxy al servidor Cloud Run
const LOCAL_SERVER = process.env.LOCAL_SERVER_URL || 'https://cabezon-server-342455707797.us-central1.run.app';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=30, stale-while-revalidate=60');
  try {
    const r = await fetch(`${LOCAL_SERVER}/dolar`, {
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    if (!r.ok) throw new Error(`Server HTTP ${r.status}`);
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'Sin datos');
    // Mapear formato servidor → formato dashboard
    const bancos = data.data.map(b => ({
      nombre: b.nombre,
      venta:  b.venta,
      mer:    b.mer,
    }));
    res.status(200).json({ ok: true, data: bancos, ts: data.ts });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
}
