const MSK_TIME_ZONE = "Europe/Moscow";
const DAY_COUNT = 7;

const state = {
  products: [],
  remoteProducts: [],
  priceHistory: {},
  expandedProductId: null,
};

const currencyFormatters = new Map();

const els = {
  status: document.querySelector("#dataStatus"),
  priceTableHead: document.querySelector("#priceTableHead"),
  priceTableBody: document.querySelector("#priceTableBody"),
  tableSummary: document.querySelector("#tableSummary"),
  addProductForm: document.querySelector("#addProductForm"),
  addProductButton: document.querySelector("#addProductButton"),
  productUrl: document.querySelector("#productUrl"),
  addProductNote: document.querySelector("#addProductNote"),
  refreshButton: document.querySelector("#refreshButton"),
};

function apiBase() {
  return String(window.PRICE_MON_API_BASE || "").replace(/\/$/, "");
}

function apiUrl(path) {
  const base = apiBase();
  if (!base) return null;
  return `${base}${path}`;
}

function detectMarketplace(url) {
  const host = new URL(url).hostname.replace(/^www\./, "").toLowerCase();
  if (host.endsWith("wildberries.ru") || host.endsWith("wb.ru")) return "wildberries";
  if (host.endsWith("ozon.ru")) return "ozon";
  if (host.endsWith("market.yandex.ru")) return "yandex_market";
  if (host.endsWith("aliexpress.ru") || host.endsWith("aliexpress.com")) return "aliexpress";
  return "generic";
}

function marketplaceLabel(value) {
  return {
    wildberries: "Wildberries",
    ozon: "Ozon",
    yandex_market: "Яндекс Маркет",
    aliexpress: "AliExpress",
    generic: "Другая площадка",
  }[value] || value;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function getFormatter(currency = "RUB") {
  if (!currencyFormatters.has(currency)) {
    currencyFormatters.set(currency, new Intl.NumberFormat("ru-RU", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }));
  }
  return currencyFormatters.get(currency);
}

function formatPrice(value, currency = "RUB") {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  try {
    return getFormatter(currency).format(value);
  } catch {
    return `${Math.round(value).toLocaleString("ru-RU")} ${currency || ""}`.trim();
  }
}

function formatShortPrice(value, currency = "RUB") {
  if (currency === "RUB" || currency === "RUR") return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
  return formatPrice(value, currency);
}

function formatMskDayKey(date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: MSK_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const data = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${data.year}-${data.month}-${data.day}`;
}

function formatDayLabel(date) {
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: MSK_TIME_ZONE,
    day: "2-digit",
    month: "short",
  }).format(date).replace(".", "");
}

function formatDateTime(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: MSK_TIME_ZONE,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value)).replace(".", "");
}

function relativeDayLabel(date) {
  const key = formatMskDayKey(date);
  const today = formatMskDayKey(new Date());
  const yesterday = formatMskDayKey(new Date(Date.now() - 24 * 60 * 60 * 1000));
  if (key === today) return "Сегодня";
  if (key === yesterday) return "Вчера";
  return formatDayLabel(date);
}

function latestObservationDate() {
  const dates = Object.values(state.priceHistory)
    .flat()
    .filter((item) => typeof item.price === "number" && item.checked_at)
    .map((item) => new Date(item.checked_at).getTime())
    .filter((time) => Number.isFinite(time));
  return new Date(dates.length ? Math.max(...dates) : Date.now());
}

function dateColumns(anchor = latestObservationDate()) {
  const anchorTime = anchor.getTime();
  return Array.from({ length: DAY_COUNT }, (_, index) => {
    const date = new Date(anchorTime - index * 24 * 60 * 60 * 1000);
    return { key: formatMskDayKey(date), label: relativeDayLabel(date) };
  });
}

function productHistory(productId) {
  return [...(state.priceHistory[productId] || [])].sort(
    (a, b) => new Date(a.checked_at) - new Date(b.checked_at),
  );
}

function validHistory(productId) {
  return productHistory(productId).filter((item) => typeof item.price === "number");
}

function lastValidObservation(history) {
  return [...history].reverse().find((item) => typeof item.price === "number");
}

function minObservation(history) {
  return history
    .filter((item) => typeof item.price === "number")
    .reduce((best, item) => (!best || item.price < best.price ? item : best), null);
}

function displayTitle(product, history) {
  const fromHistory = [...history].reverse().find((item) => item.title)?.title;
  return fromHistory || product.title || product.url;
}

function priceByDay(history) {
  const map = new Map();
  history.forEach((item) => {
    if (typeof item.price !== "number" || !item.checked_at) return;
    map.set(formatMskDayKey(new Date(item.checked_at)), item);
  });
  return map;
}

function emptyRow(colspan, message) {
  const row = document.createElement("tr");
  row.className = "empty-row";
  row.innerHTML = `<td colspan="${colspan}">${escapeHtml(message)}</td>`;
  return row;
}

function renderTable() {
  const columns = dateColumns(latestObservationDate());
  els.priceTableHead.innerHTML = `
    <tr>
      <th scope="col">Товар</th>
      ${columns.map((day) => `<th scope="col">${escapeHtml(day.label)}</th>`).join("")}
    </tr>
  `;
  els.priceTableBody.innerHTML = "";

  if (!state.products.length) {
    els.tableSummary.textContent = "Пока нет товаров";
    els.priceTableBody.append(emptyRow(columns.length + 1, "Добавьте ссылку на карточку товара, чтобы начать наблюдение."));
    return;
  }

  const observedCount = Object.values(state.priceHistory).reduce((sum, history) => sum + history.length, 0);
  els.tableSummary.textContent = `${state.products.length} товаров · ${observedCount} наблюдений · до ${formatDayLabel(latestObservationDate())}`;

  state.products.forEach((product) => {
    const history = productHistory(product.id);
    const valid = validHistory(product.id);
    const byDay = priceByDay(valid);
    const latest = lastValidObservation(history);
    const best = minObservation(valid);
    const host = new URL(product.url).hostname.replace(/^www\./, "");
    const marketplace = product.marketplace || detectMarketplace(product.url);
    const title = displayTitle(product, history);
    const isExpanded = state.expandedProductId === product.id;
    const statusLabel = product.active === false ? "пауза" : marketplaceLabel(marketplace);

    const row = document.createElement("tr");
    row.className = `price-row ${isExpanded ? "expanded" : ""}`;
    row.tabIndex = 0;
    row.innerHTML = `
      <td>
        <div class="product-cell">
          <span class="chevron" aria-hidden="true">${isExpanded ? "▾" : "▸"}</span>
          <div>
            <span class="product-name">${escapeHtml(title)}</span>
            <span class="product-subline">
              <span>${escapeHtml(host)}</span>
              <span class="badge">${escapeHtml(statusLabel)}</span>
            </span>
          </div>
        </div>
      </td>
      ${columns.map((day) => {
        const observation = byDay.get(day.key);
        const isBest = observation && best && observation.checked_at === best.checked_at && observation.price === best.price;
        const classes = `price-value ${observation ? "" : "missing"} ${isBest ? "best" : ""}`.trim();
        return `<td><span class="${classes}">${escapeHtml(observation ? formatShortPrice(observation.price, observation.currency || product.currency) : "-")}</span></td>`;
      }).join("")}
    `;
    row.addEventListener("click", () => toggleProduct(product.id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleProduct(product.id);
      }
    });
    els.priceTableBody.append(row);

    if (isExpanded) {
      const detailRow = document.createElement("tr");
      detailRow.className = "details-row";
      detailRow.innerHTML = detailTemplate(product, history, latest, best, columns.length + 1);
      els.priceTableBody.append(detailRow);
      const canvas = detailRow.querySelector("canvas");
      requestAnimationFrame(() => drawChart(canvas, valid, latest?.currency || product.currency || "RUB"));
    }
  });
}

function detailTemplate(product, history, latest, best, colspan) {
  const currency = latest?.currency || product.currency || "RUB";
  const title = displayTitle(product, history);
  return `
    <td colspan="${colspan}">
      <div class="expanded-panel">
        <div class="chart-card">
          <div class="chart-title">
            <h3>${escapeHtml(title)}</h3>
            <span>${history.length ? `${history.length} точек` : "ожидаем первое обновление"}</span>
          </div>
          <canvas class="inline-chart" width="980" height="300" aria-label="График цены"></canvas>
        </div>
        <div class="detail-metrics">
          <div class="metric"><span>Сейчас</span><strong>${escapeHtml(latest ? formatPrice(latest.price, currency) : "-")}</strong></div>
          <div class="metric best"><span>Минимум</span><strong>${escapeHtml(best ? formatPrice(best.price, best.currency || currency) : "-")}</strong></div>
          <div class="metric"><span>Точек</span><strong>${history.length}</strong></div>
          <div class="metric"><span>Обновлено</span><strong>${escapeHtml(latest ? formatDateTime(latest.checked_at) : "-")}</strong></div>
          <a class="open-link" href="${escapeHtml(product.url)}" target="_blank" rel="noreferrer">Открыть</a>
        </div>
      </div>
    </td>
  `;
}

function toggleProduct(productId) {
  state.expandedProductId = state.expandedProductId === productId ? null : productId;
  renderTable();
}

function drawChart(canvas, history, currency = "RUB") {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const padding = { top: 48, right: 34, bottom: 46, left: 70 };
  const points = history.filter((item) => typeof item.price === "number");

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  if (!points.length) {
    ctx.fillStyle = "#6f776d";
    ctx.font = "18px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("Ждём первое наблюдение", width / 2, height / 2);
    return;
  }

  const prices = points.map((item) => item.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = Math.max(max - min, 1);
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (points.length === 1 ? plotWidth / 2 : (plotWidth * index) / (points.length - 1));
  const y = (price) => padding.top + plotHeight - ((price - min) / span) * plotHeight;

  ctx.strokeStyle = "rgba(28, 33, 29, 0.1)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i += 1) {
    const lineY = padding.top + (plotHeight * i) / 4;
    ctx.moveTo(padding.left, lineY);
    ctx.lineTo(width - padding.right, lineY);
  }
  ctx.stroke();

  ctx.strokeStyle = "#10796f";
  ctx.lineWidth = 3;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(index);
    const py = y(point.price);
    if (index === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.stroke();

  const best = minObservation(points);
  points.forEach((point, index) => {
    const px = x(index);
    const py = y(point.price);
    const isBest = best && point.checked_at === best.checked_at && point.price === best.price;
    ctx.fillStyle = isBest ? "#a94f08" : "#10796f";
    ctx.beginPath();
    ctx.arc(px, py, isBest ? 5 : 4, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = isBest ? "#8a3d05" : "#4c554b";
    ctx.font = "12px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText(formatShortPrice(point.price, currency), px, Math.max(16, py - 9));
  });

  ctx.fillStyle = "#6f776d";
  ctx.font = "12px Inter, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  [min, max].forEach((price) => ctx.fillText(formatShortPrice(price, currency), padding.left - 10, y(price)));

  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  labelIndexes.forEach((index) => ctx.fillText(formatDayLabel(new Date(points[index].checked_at)), x(index), height - 28));
}

function applyState(payload) {
  state.remoteProducts = payload.products || [];
  state.products = state.remoteProducts;
  state.priceHistory = payload.prices || {};
  state.expandedProductId = state.products.find((item) => item.active !== false)?.id || state.products[0]?.id || null;
  renderTable();
}

function setNote(message, type = "") {
  els.addProductNote.textContent = message;
  els.addProductNote.className = `note ${type}`.trim();
}

async function addProduct(url) {
  const endpoint = apiUrl("/api/products");
  if (!endpoint) throw new Error("Backend API не подключён");

  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "Backend не добавил товар");
  return payload;
}

async function refreshPrices() {
  const endpoint = apiUrl("/api/refresh");
  if (!endpoint) {
    window.open("https://github.com/Alati-elle/price-mon/actions/workflows/update-prices.yml", "_blank", "noreferrer");
    setNote("Открыла ручной запуск обновления в GitHub Actions.");
    return;
  }

  const response = await fetch(endpoint, { method: "POST" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    window.open("https://github.com/Alati-elle/price-mon/actions/workflows/update-prices.yml", "_blank", "noreferrer");
    throw new Error(payload.error || "Открыла ручной запуск в GitHub Actions");
  }
  setNote("Ручное обновление запущено. Данные появятся после завершения workflow.", "success");
}

async function loadData() {
  try {
    const stateEndpoint = apiUrl("/api/state");
    if (stateEndpoint) {
      const response = await fetch(stateEndpoint, { cache: "no-store" });
      if (response.ok) {
        applyState(await response.json());
        els.status.textContent = "API подключён";
        return;
      }
    }

    const [productsResponse, pricesResponse] = await Promise.all([
      fetch("data/products.json", { cache: "no-store" }),
      fetch("data/prices.json", { cache: "no-store" }),
    ]);
    if (!productsResponse.ok || !pricesResponse.ok) throw new Error("Не удалось загрузить JSON");
    applyState({ products: await productsResponse.json(), prices: await pricesResponse.json() });
    els.status.textContent = stateEndpoint ? "API недоступен" : "Только чтение";
  } catch (error) {
    els.status.textContent = "Ошибка данных";
    els.tableSummary.textContent = "Не удалось загрузить данные";
    els.priceTableBody.innerHTML = "";
    els.priceTableBody.append(emptyRow(DAY_COUNT + 1, error.message));
  }
}

els.refreshButton.addEventListener("click", async () => {
  els.refreshButton.disabled = true;
  els.refreshButton.textContent = "Запускаю";
  try {
    await refreshPrices();
  } catch (error) {
    setNote(error.message, "error");
  } finally {
    els.refreshButton.disabled = false;
    els.refreshButton.textContent = "Обновить цены";
  }
});

els.addProductForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = els.productUrl.value.trim();
  if (!url) return;

  try {
    new URL(url);
  } catch {
    setNote("Нужна полная ссылка на карточку товара.", "error");
    return;
  }

  els.addProductButton.disabled = true;
  els.addProductButton.textContent = "Добавляю";
  setNote("Добавляю товар через backend...");
  try {
    const payload = await addProduct(url);
    applyState(payload);
    els.productUrl.value = "";
    setNote("Товар добавлен и сохранён.", "success");
    els.status.textContent = "API подключён";
  } catch (error) {
    setNote(error.message, "error");
  } finally {
    els.addProductButton.disabled = false;
    els.addProductButton.textContent = "Добавить";
  }
});

loadData();
