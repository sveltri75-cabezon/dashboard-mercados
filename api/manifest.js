// api/manifest.js
export default function handler(req, res) {
  res.setHeader('Content-Type', 'application/manifest+json');
  res.setHeader('Cache-Control', 'no-cache');
  res.status(200).json({
    name: "Mercados BM",
    short_name: "Mercados BM",
    description: "Dashboard de mercados financieros — Banco Meridian",
    start_url: "/",
    display: "standalone",
    background_color: "#060910",
    theme_color: "#060910",
    orientation: "any",
    icons: [
      { src: "/public/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/public/icon-512.png", sizes: "512x512", type: "image/png" }
    ]
  });
}
