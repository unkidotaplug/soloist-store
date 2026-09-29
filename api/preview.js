const SITE_URL = "https://soloist-store.vercel.app";
const FALLBACK_IMAGE = `${SITE_URL}/assets/og.jpg`;

function clean(value, limit) {
  return String(value ?? "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function safeImage(value) {
  try {
    const url = new URL(String(value ?? ""));
    return ["http:", "https:"].includes(url.protocol) ? url.toString() : FALLBACK_IMAGE;
  } catch {
    return FALLBACK_IMAGE;
  }
}

export default function handler(request, response) {
  if (request.method !== "GET") {
    response.setHeader("Allow", "GET");
    return response.status(405).send("Method not allowed");
  }

  const title = clean(request.query.title, 180) || "SOLOIST";
  const image = safeImage(request.query.image);
  const previewImage = image.startsWith(SITE_URL)
    ? image
    : `${SITE_URL}/api/image?url=${encodeURIComponent(image)}`;
  const canonical = new URL(`${SITE_URL}/api/preview`);
  canonical.searchParams.set("title", title);
  canonical.searchParams.set("image", image);

  const safeTitle = escapeHtml(title);
  const safeImageUrl = escapeHtml(previewImage);
  const safeCanonical = escapeHtml(canonical.toString());
  response.setHeader("Content-Type", "text/html; charset=utf-8");
  response.setHeader("Cache-Control", "public, max-age=60, s-maxage=300");
  return response.status(200).send(`<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>${safeTitle}</title>
  <link rel="canonical" href="${safeCanonical}">
  <link rel="icon" href="${SITE_URL}/assets/favicon-32.png">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="SOLOIST">
  <meta property="og:title" content="${safeTitle}">
  <meta property="og:url" content="${safeCanonical}">
  <meta property="og:image" content="${safeImageUrl}">
  <meta property="og:image:secure_url" content="${safeImageUrl}">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:width" content="1080">
  <meta property="og:image:height" content="1350">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="${safeTitle}">
  <meta name="twitter:image" content="${safeImageUrl}">
</head>
<body style="margin:0;background:#111;color:#fff;font-family:Arial,sans-serif">
  <main style="max-width:900px;margin:0 auto">
    <h1 style="padding:32px;margin:0">${safeTitle}</h1>
    <img src="${safeImageUrl}" alt="${safeTitle}" style="display:block;width:100%;height:auto">
  </main>
</body>
</html>`);
}
