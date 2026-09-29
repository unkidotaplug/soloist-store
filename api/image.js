const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

function allowedSource(value) {
  try {
    const url = new URL(String(value ?? ""));
    if (url.protocol !== "https:") return null;
    const host = url.hostname.toLowerCase();
    if (host === "telesco.pe" || host.endsWith(".telesco.pe")) return url;
    return null;
  } catch {
    return null;
  }
}

export default async function handler(request, response) {
  if (!['GET', 'HEAD'].includes(request.method)) {
    response.setHeader("Allow", "GET, HEAD");
    return response.status(405).send("Method not allowed");
  }

  const source = allowedSource(request.query.url);
  if (!source) return response.status(400).send("Unsupported image source");

  try {
    const upstream = await fetch(source, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; SOLOISTPreview/1.0)",
        Accept: "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8",
      },
      redirect: "follow",
    });
    if (!upstream.ok) return response.status(502).send("Upstream image unavailable");
    const contentType = upstream.headers.get("content-type") || "";
    if (!contentType.startsWith("image/")) return response.status(415).send("Upstream is not an image");
    const data = Buffer.from(await upstream.arrayBuffer());
    if (!data.length || data.length > MAX_IMAGE_BYTES) {
      return response.status(413).send("Image is empty or too large");
    }

    response.setHeader("Content-Type", contentType.split(";", 1)[0]);
    response.setHeader("Content-Length", String(data.length));
    response.setHeader("Cache-Control", "public, max-age=86400, s-maxage=31536000, immutable");
    if (request.method === "HEAD") return response.status(200).end();
    return response.status(200).send(data);
  } catch {
    return response.status(502).send("Image proxy failed");
  }
}
