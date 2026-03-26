// api/lici.js
// Busca la última licitación publicada en argentina.gob.ar/noticias/
// Parsea fecha de recepción, liquidación e instrumentos

const BASE_URL = 'https://www.argentina.gob.ar';
const SEARCH_URL = `${BASE_URL}/noticias/llamado-licitacion-de-instrumentos-del-tesoro-nacional-denominados-en-pesos-y-en-dolares`;

// Candidatos de URLs a revisar (el gobierno usa sufijos numéricos -0, -1, -2, etc.)
const SLUG_BASE = '/noticias/llamado-licitacion-de-instrumentos-del-tesoro-nacional-denominados-en-pesos-y';

const MESES_ES = {
  'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
  'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12
};

function parseFechaTexto(texto) {
  // "día DD de MES de YYYY"
  const m = texto.match(/(\d{1,2})\s+de\s+([a-záéíóúü]+)\s+de\s+(\d{4})/i);
  if (!m) return null;
  const dia = parseInt(m[1]);
  const mes = MESES_ES[m[2].toLowerCase()];
  const anio = parseInt(m[3]);
  if (!mes) return null;
  return new Date(anio, mes - 1, dia);
}

function formatFecha(d) {
  if (!d) return null;
  const meses = ['ENE','FEB','MAR','ABR','MAY','JUN','JUL','AGO','SEP','OCT','NOV','DIC'];
  return `${d.getDate()} ${meses[d.getMonth()]}`;
}

function parsearInstrumentos(html) {
  const tipos = [];
  const texto = html.replace(/<[^>]+>/g, ' ').toUpperCase();

  if (/LECAP|CAPITALIZABLE EN PESOS/.test(texto))   tipos.push({ label: 'Tasa Fija', type: 'lt-fija' });
  if (/LECER|BONCER|AJUSTE POR CER/.test(texto))    tipos.push({ label: 'CER',       type: 'lt-cer'  });
  if (/TAMAR/.test(texto))                           tipos.push({ label: 'TAMAR',     type: 'lt-tamar'});
  if (/DÓLAR LINKED|DOLLAR LINKED|LELINK|VINCULAD/.test(texto)) tipos.push({ label: 'DL', type: 'lt-link' });
  if (/BONAR|DÓLARES ESTADOUNIDENSES.*SUSCRIPCIÓN/.test(texto)) tipos.push({ label: 'USD', type: 'lt-usd' });

  return tipos;
}

async function fetchNoticia(url) {
  try {
    const r = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html',
        'Accept-Language': 'es-AR,es;q=0.9',
      }
    });
    if (!r.ok) return null;
    return await r.text();
  } catch { return null; }
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=7200');

  // Intentar sufijos del más reciente al más viejo: -4, -3, -2, -1, -0, sin sufijo
  const slugs = [
    `${SLUG_BASE}-en-dolares-4`,
    `${SLUG_BASE}-en-dolares-3`,
    `${SLUG_BASE}-en-dolares-2`,
    `${SLUG_BASE}-en-dolares-1`,
    `${SLUG_BASE}-en-dolares-0`,
    `${SLUG_BASE}-en-dolares`,
    `${SLUG_BASE}-dolares-estadounidenses-4`,
    `${SLUG_BASE}-dolares-estadounidenses-3`,
    `${SLUG_BASE}-dolares-estadounidenses-2`,
    `${SLUG_BASE}-dolares-estadounidenses-1`,
    `${SLUG_BASE}-dolares-estadounidenses-0`,
    `${SLUG_BASE}-dolares-estadounidenses`,
  ];

  const today = new Date();
  today.setHours(0,0,0,0);

  let resultado = null;

  for (const slug of slugs) {
    const html = await fetchNoticia(`${BASE_URL}${slug}`);
    if (!html) continue;

    // Buscar fecha de publicación de la noticia
    const pubMatch = html.match(/(\d{1,2})\s+de\s+([a-záéíóúü]+)\s+de\s+(\d{4})/i);
    const pubFecha = pubMatch ? parseFechaTexto(pubMatch[0]) : null;
    if (!pubFecha) continue;

    // Solo considerar noticias de los últimos 90 días
    const diffDias = (today - pubFecha) / 86400000;
    if (diffDias > 90) continue;

    // Buscar fecha de recepción: "finalizará a las 15:00 horas del día X de MES de YYYY"
    const recepMatch = html.match(/finalizar[aá]\s+a\s+las\s+15[:\.]?00\s+horas?\s+del\s+d[ií]a\s+([\w\s]+de\s+\d{4})/i);
    const recepFecha = recepMatch ? parseFechaTexto(recepMatch[1]) : null;

    // Buscar fecha de liquidación: "liquidación ... efectuará el día X de MES de YYYY"
    const liqMatch = html.match(/liquidaci[oó]n[^.]*efectuar[aá]\s+el\s+d[ií]a\s+([\w\s]+de\s+\d{4})/i);
    const liqFecha = liqMatch ? parseFechaTexto(liqMatch[1]) : null;

    if (!recepFecha) continue;

    // Determinar estado
    const recepClose = new Date(recepFecha);
    recepClose.setHours(15, 0, 0, 0);
    const ahora = new Date();

    let estado;
    if (ahora < new Date(recepFecha).setHours(10,0,0,0)) estado = 'proxima';
    else if (ahora <= recepClose)                          estado = 'activa';
    else                                                   estado = 'cerrada';

    const instrumentos = parsearInstrumentos(html);

    resultado = {
      estado,
      recepcion:    formatFecha(recepFecha),
      liquidacion:  liqFecha ? formatFecha(liqFecha) : null,
      recepcionISO: recepFecha.toISOString(),
      liqISO:       liqFecha  ? liqFecha.toISOString() : null,
      instrumentos,
      url: `${BASE_URL}${slug}`,
      ts: new Date().toISOString(),
    };

    // Si encontramos una futura o activa, usar esa. Si es cerrada, seguir buscando una más nueva.
    if (estado !== 'cerrada') break;
    // Guardar la cerrada más reciente pero seguir buscando
    // (el bucle va de más reciente a más viejo, así que la primera cerrada que encontremos es la más reciente)
    break;
  }

  if (!resultado) {
    return res.status(200).json({ ok: true, data: null }); // sin licitación publicada
  }

  res.status(200).json({ ok: true, data: resultado });
}
