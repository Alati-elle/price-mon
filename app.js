const state = {
  products: [],
  priceHistory: {},
  selectedProductId: null,
};

const currencyFormatters = new Map();

const els = {
  status: document.querySelector("#dataStatus"),
  productCount: document.querySelector("#productCount"),
  products: document.querySelector("#products"),
  emptyState: document.querySelector("#emptyState"),
  productDetails: document.querySelector("#productDetails"),
  storeName: document.querySelector("#storeName"),
  productTitle: document.querySelector("#productTitle"),
  productLink: document.querySelector("#productLink"),
  currentPrice: document.querySelector("#currentPrice"),
  minPrice: document.querySelector("#minPrice"),
  observationCount: document.querySelector("#observationCount"),
  updatedAt: document.querySelector("#updatedAt"),
  historyRows: document.querySelector("#historyRows"),
  chart: document.querySelector("#priceChart"),
  addProductForm: document.querySelector("#addProductForm"),
  productUrl: document.querySelector("#productUrl"),
  addProductNote: document.querySelector("#addProductNote"),
};

function getFormatter(currency = "RUB") {
  if (!currencyFormatters.has(currency)) {
    currencyFormatters.set(
      currency,
      new Intl.NumberFormat("ru-RU", {
        style: "currency",
        currency,
        maximumFractionDigits: 0,
      }),
    );
  }

  return currencyFormatters.get(currency);
}

function formatPrice(value, currency) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }

  try {
    return getFormatter(currency).format(value);
  } catch {
    return `${value.toLocaleString("ru-RU")} ${currency || ""}`.trim();
  }
}

function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function productHistory(productId) {
  return [...(state.priceHistory[productId] || [])].sort(
    (a, b) => new Date(a.checked_at) - new Date(b.checked_at),
  );
}

function lastValidObservation(history) {
  return [...history].reverse().find((item) => typeof item.price === "number");
}

function minObservation(history) {
  return history
    .filter((item) => typeof item.price === "number")
    .reduce((best, item) => (!best || item.price < best.price ? item : best), null);
}

function renderProducts() {
  els.productCount.textContent = state.products.length;
  els.products.innerHTML = "";

  state.products.forEach((product) => {
    const history = productHistory(product.id);
    const latest = lastValidObservation(history);
    const button = document.createElement("button");
    button.className = `product-button ${product.id === state.selectedProductId ? "active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <strong>${product.title || product.url}</strong>
      <span>${product.store || new URL(product.url).hostname}</span>
      <span>${latest ? formatPrice(latest.price, latest.currency || product.currency) : "Пока нет цены"}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedProductId = product.id;
      render();
    });
    els.products.append(button);
  });
}

function renderDetails() {
  const product = state.products.find((item) => item.id === state.selectedProductId);
  if (!product) {
    els.emptyState.classList.remove("hidden");
    els.productDetails.classList.add("hidden");
    drawChart([]);
    return;
  }

  const history = productHistory(product.id);
  const latest = lastValidObservation(history);
  const best = minObservation(history);
  const currency = latest?.currency || product.currency || "RUB";

  els.emptyState.classList.add("hidden");
  els.productDetails.classList.remove("hidden");
  els.storeName.textContent = product.store || new URL(product.url).hostname;
  els.productTitle.textContent = product.title || product.url;
  els.productLink.href = product.url;
  els.currentPrice.textContent = latest ? formatPrice(latest.price, currency) : "-";
  els.minPrice.textContent = best ? `${formatPrice(best.price, best.currency || currency)} · ${formatDate(best.checked_at)}` : "-";
  els.observationCount.textContent = history.length;
  els.updatedAt.textContent = latest ? formatDate(latest.checked_at) : "-";

  els.historyRows.innerHTML = "";
  [...history].reverse().forEach((item) => {
    const row = document.createElement("tr");
    if (best && item.checked_at === best.checked_at && item.price === best.price) {
      row.className = "best-row";
    }

    row.innerHTML = `
      <td>${formatDate(item.checked_at)}</td>
      <td>${formatPrice(item.price, item.currency || currency)}</td>
      <td class="${item.status === "error" ? "error" : ""}">${item.message || item.status || "ok"}</td>
    `;
    els.historyRows.append(row);
  });

  drawChart(history, currency);
}

function drawChart(history, currency = "RUB") {
  const ctx = els.chart.getContext("2d");
  const width = els.chart.width;
  const height = els.chart.height;
  const padding = { top: 28, right: 24, bottom: 58, left: 76 };
  const points = history.filter((item) => typeof item.price === "number");

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  if (points.length === 0) {
    ctx.fillStyle = "#6b736d";
    ctx.font = "24px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Нет данных для графика", width / 2, height / 2);
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

  ctx.strokeStyle = "#dce3dc";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i += 1) {
    const lineY = padding.top + (plotHeight * i) / 4;
    ctx.moveTo(padding.left, lineY);
    ctx.lineTo(width - padding.right, lineY);
  }
  ctx.stroke();

  ctx.strokeStyle = "#0f766e";
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(index);
    const py = y(point.price);
    if (index === 0) {
      ctx.moveTo(px, py);
    } else {
      ctx.lineTo(px, py);
    }
  });
  ctx.stroke();

  const best = minObservation(points);
  points.forEach((point, index) => {
    const isBest = best && point.checked_at === best.checked_at && point.price === best.price;
    ctx.fillStyle = isBest ? "#b45309" : "#0f766e";
    ctx.beginPath();
    ctx.arc(x(index), y(point.price), isBest ? 8 : 5, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#6b736d";
  ctx.font = "18px Inter, sans-serif";
  ctx.textAlign = "right";
  [min, max].forEach((price) => {
    ctx.fillText(formatPrice(price, currency), padding.left - 12, y(price) + 6);
  });

  ctx.textAlign = "center";
  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  labelIndexes.forEach((index) => {
    ctx.fillText(formatDate(points[index].checked_at), x(index), height - 20);
  });
}

function render() {
  renderProducts();
  renderDetails();
}

async function loadData() {
  try {
    const [productsResponse, pricesResponse] = await Promise.all([
      fetch("data/products.json", { cache: "no-store" }),
      fetch("data/prices.json", { cache: "no-store" }),
    ]);

    if (!productsResponse.ok || !pricesResponse.ok) {
      throw new Error("Не удалось загрузить JSON");
    }

    state.products = await productsResponse.json();
    state.priceHistory = await pricesResponse.json();
    state.selectedProductId = state.products[0]?.id || null;
    els.status.textContent = "Данные загружены";
    render();
  } catch (error) {
    els.status.textContent = "Ошибка данных";
    els.emptyState.innerHTML = `<h2>Не удалось загрузить данные</h2><p>${error.message}</p>`;
  }
}

els.addProductForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const url = els.productUrl.value.trim();
  if (!url) {
    return;
  }

  const parsed = new URL(url);
  const id = parsed.hostname.replace(/^www\./, "").replace(/[^a-z0-9]+/gi, "-").toLowerCase() + "-" + Date.now();
  const product = {
    id,
    title: parsed.hostname,
    url,
    store: parsed.hostname.replace(/^www\./, ""),
    currency: "RUB",
    active: true,
  };

  els.addProductNote.textContent = JSON.stringify(product, null, 2);
  els.productUrl.value = "";
});

loadData();
