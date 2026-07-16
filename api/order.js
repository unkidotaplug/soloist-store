const MAX_TEXT = 500;
const MAX_ITEMS = 30;

function clean(value, limit = MAX_TEXT) {
  return String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, limit);
}

export default async function handler(request, response) {
  if (request.method !== "POST") {
    response.setHeader("Allow", "POST");
    return response.status(405).json({ ok: false, error: "Method not allowed" });
  }

  const token = process.env.TELEGRAM_ORDER_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_ORDER_CHAT_ID;
  if (!token || !chatId) {
    return response.status(503).json({ ok: false, error: "Order service is not configured" });
  }

  const body = request.body && typeof request.body === "object" ? request.body : {};
  const name = clean(body.name, 120);
  const address = clean(body.address, 300);
  const telegram = clean(body.telegram, 80).replace(/^@/, "");
  const comment = clean(body.comment, 500);
  const items = Array.isArray(body.items) ? body.items.slice(0, MAX_ITEMS) : [];

  if (!name || !address || !telegram || !items.length) {
    return response.status(400).json({ ok: false, error: "Required fields are missing" });
  }

  const itemLines = items.map((item) => {
    const brand = clean(item.brand, 100);
    const productName = clean(item.name, 160);
    const quantity = Math.max(1, Math.min(99, Number.parseInt(item.quantity, 10) || 1));
    const price = Math.max(0, Number.parseInt(item.price, 10) || 0);
    return `• ${brand} ${productName} × ${quantity} = ${(price * quantity).toLocaleString("ru-RU")} ₽`;
  });
  const total = Math.max(0, Number.parseInt(body.total, 10) || 0);
  const text = [
    "🛍 НОВЫЙ ЗАКАЗ — SOLOIST",
    "",
    `👤 Имя: ${name}`,
    `📦 Адрес доставки: ${address}`,
    `💬 Telegram: @${telegram}`,
    ...(comment ? [`📝 Комментарий: ${comment}`] : []),
    "",
    "Состав заказа:",
    ...itemLines,
    "",
    `💰 Итого: ${total.toLocaleString("ru-RU")} ₽`,
  ].join("\n");

  try {
    const telegramResponse = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
    });
    const result = await telegramResponse.json();
    if (!telegramResponse.ok || !result.ok) {
      throw new Error(result.description || "Telegram request failed");
    }
    return response.status(200).json({ ok: true });
  } catch (error) {
    console.error("Order delivery failed", error instanceof Error ? error.message : error);
    return response.status(502).json({ ok: false, error: "Order delivery failed" });
  }
}
