# Dashboard Mercados Argentina

Dashboard financiero en tiempo real para TV/Samsung DeX.

## Estructura

```
dashboard-mercados/
├── index.html          # Dashboard principal
├── vercel.json         # Configuración Vercel
├── api/
│   ├── bonds.js        # Proxy → data912 bonos (CORS)
│   ├── stocks.js       # Proxy → data912 acciones (CORS)
│   ├── tamar.js        # Proxy → BCRA TAMAR var.44
│   └── bcra-pf.js      # Scraping → BCRA plazo fijo online
└── README.md
```

## Deploy en Vercel (pasos)

### 1. Subir a GitHub
```bash
git init
git add .
git commit -m "init dashboard"
git remote add origin https://github.com/TU_USUARIO/dashboard-mercados.git
git push -u origin main
```

### 2. Conectar a Vercel
1. Ir a https://vercel.com → New Project
2. Importar el repo de GitHub
3. Framework Preset: **Other**
4. Click **Deploy**

### 3. Abrir en Samsung DeX
- Abrir Chrome en DeX
- Ir a la URL de Vercel (ej: `https://dashboard-mercados.vercel.app`)
- F11 para pantalla completa

## Fuentes de datos

| Tarjeta | Fuente | Refresco |
|---|---|---|
| Dólar MEP | data912 (AL30/AL30D) via `/api/bonds` | 10s |
| Dólar CCL | data912 (AL30/AL30C) via `/api/bonds` | 10s |
| Tasa TAMAR | BCRA API var.44 via `/api/tamar` | 5min |
| Tasa Fija / CER | CSV Google Sheets + data912 precios | 10s |
| Hard Dólar | CSV Google Sheets flujos + data912 precios | 10s |
| Plazo Fijo Web | BCRA scraping via `/api/bcra-pf` | 5min |
| Dólar Bancos | Mock (pendiente scraping Meridian/Plus) | — |
| Lici MECON | Hardcoded (pendiente scraping arg.gob.ar) | manual |
| Ticker Merval | data912 via `/api/stocks` | 10s |

## Pendientes para v2
- [ ] Scraping Meridian/Plus Cambio para Dólar Bancos
- [ ] Scraping automático Lici MECON desde argentina.gob.ar
- [ ] Gráficos históricos reales MEP/CCL desde data912/historical
