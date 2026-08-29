const DEFAULT_REPOSITORY = "Alati-elle/price-mon";
const DEFAULT_BRANCH = "main";

const MARKETPLACE_LABELS = {
  wildberries: "Wildberries",
  ozon: "Ozon",
  yandex_market: "Яндекс Маркет",
  aliexpress: "AliExpress",
  generic: "Другая площадка",
};

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    try {
      const url = new URL(request.url);
      if (url.pathname === "/api/health") return json({ ok: true }, 200, cors);
      if (url.pathname === "/api/state" && request.method === "GET") return json(await readState(env), 200, cors);
      if (url.pathname === "/api/products" && request.method === "POST") return json(await addProduct(request, env), 200, cors);
      return json({ error: "Not found" }, 404, cors);
    } catch (error) {
      return json({ error: error.message || "Internal error" }, error.status || 500, cors);
    }
  },
};

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "*";
  const allowed = (env.ALLOWED_ORIGINS || "*").split(",").map((item) => item.trim()).filter(Boolean);
  const allowOrigin = allowed.includes("*") || allowed.includes(origin) ? origin : allowed[0] || origin;
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value, null, 2), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

function requireEnv(env, key) {
  const value = env[key];
  if (!value) {
    const error = new Error(`Missing env ${key}`);
    error.status = 500;
    throw error;
  }
  return value;
}

function requireAuth(request, env) {
  const expected = requireEnv(env, "ADMIN_TOKEN");
  const header = request.headers.get("Authorization") || "";
  const actual = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!actual || actual !== expected) {
    const error = new Error("Invalid API key");
    error.status = 401;
    throw error;
  }
}

function githubConfig(env) {
  return {
    repository: env.GITHUB_REPOSITORY || DEFAULT_REPOSITORY,
    branch: env.GITHUB_BRANCH || DEFAULT_BRANCH,
    token: requireEnv(env, "GITHUB_TOKEN"),
  };
}

async function githubFetch(env, path, init = {}) {
  const { repository, token } = githubConfig(env);
  const response = await fetch(`https://api.github.com/repos/${repository}${path}`, {
    ...init,
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${token}`,
      "User-Agent": "price-mon-worker",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`GitHub API ${response.status}: ${text.slice(0, 220)}`);
  }
  return response.status === 204 ? null : response.json();
}

function decodeBase64Json(content) {
  const raw = atob(content.replace(/\n/g, ""));
  const bytes = Uint8Array.from(raw, (char) => char.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

async function readJsonFile(env, path, fallback) {
  const { branch } = githubConfig(env);
  try {
    const file = await githubFetch(env, `/contents/${path}?ref=${encodeURIComponent(branch)}`);
    return decodeBase64Json(file.content);
  } catch (error) {
    if (String(error.message).includes("GitHub API 404")) return fallback;
    throw error;
  }
}

async function readState(env) {
  const [products, prices] = await Promise.all([
    readJsonFile(env, "data/products.json", []),
    readJsonFile(env, "data/prices.json", {}),
  ]);
  return { products, prices };
}

async function commitFiles(env, files, message) {
  const { branch } = githubConfig(env);
  const ref = await githubFetch(env, `/git/ref/heads/${encodeURIComponent(branch)}`);
  const baseSha = ref.object.sha;
  const commit = await githubFetch(env, `/git/commits/${baseSha}`);

  const treeEntries = [];
  for (const [path, content] of Object.entries(files)) {
    const blob = await githubFetch(env, "/git/blobs", {
      method: "POST",
      body: JSON.stringify({ content, encoding: "utf-8" }),
    });
    treeEntries.push({ path, mode: "100644", type: "blob", sha: blob.sha });
  }

  const tree = await githubFetch(env, "/git/trees", {
    method: "POST",
    body: JSON.stringify({ base_tree: commit.tree.sha, tree: treeEntries }),
  });
  const nextCommit = await githubFetch(env, "/git/commits", {
    method: "POST",
    body: JSON.stringify({ message, tree: tree.sha, parents: [baseSha] }),
  });
  await githubFetch(env, `/git/refs/heads/${encodeURIComponent(branch)}`, {
    method: "PATCH",
    body: JSON.stringify({ sha: nextCommit.sha }),
  });
  return nextCommit.sha;
}

async function addProduct(request, env) {
  requireAuth(request, env);
  const body = await request.json().catch(() => ({}));
  const url = normalizeProductUrl(body.url);
  const marketplace = detectMarketplace(url);
  const parsed = new URL(url);
  const productId = productIdFromUrl(url);
  const state = await readState(env);
  const products = Array.isArray(state.products) ? state.products : [];
  const prices = state.prices && typeof state.prices === "object" ? state.prices : {};

  let product = products.find((item) => item.id === productId || item.url === url);
  const checkedAt = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const observation = await buildObservation(url, marketplace, checkedAt);

  if (product) {
    product.active = true;
    product.marketplace ||= marketplace;
    product.currency ||= observation.currency || "RUB";
    if (observation.title) product.title = observation.title;
  } else {
    product = {
      id: productId,
      title: observation.title || MARKETPLACE_LABELS[marketplace] || marketplace,
      url,
      store: parsed.hostname.replace(/^www\./, ""),
      marketplace,
      currency: observation.currency || "RUB",
      active: true,
    };
    products.unshift(product);
  }

  prices[product.id] ||= [];
  prices[product.id].push(observation);

  const commitSha = await commitFiles(env, {
    "data/products.json": `${JSON.stringify(products, null, 2)}\n`,
    "data/prices.json": `${JSON.stringify(prices, null, 2)}\n`,
  }, `Add product ${product.id}`);

  return { product, products, prices, observation, commit_sha: commitSha };
}

function normalizeProductUrl(value) {
  if (!value || typeof value !== "string") throw badRequest("Product URL is required");
  let parsed;
  try {
    parsed = new URL(value.trim());
  } catch {
    throw badRequest("Product URL must be an absolute http(s) link");
  }
  if (!["http:", "https:"].includes(parsed.protocol)) throw badRequest("Product URL must be http(s)");
  return parsed.toString();
}

function badRequest(message) {
  const error = new Error(message);
  error.status = 400;
  return error;
}

function detectMarketplace(url) {
  const host = new URL(url).hostname.replace(/^www\./, "").toLowerCase();
  if (host.endsWith("wildberries.ru") || host.endsWith("wb.ru")) return "wildberries";
  if (host.endsWith("ozon.ru")) return "ozon";
  if (host.endsWith("market.yandex.ru")) return "yandex_market";
  if (host.endsWith("aliexpress.ru") || host.endsWith("aliexpress.com")) return "aliexpress";
  return "generic";
}

function productIdFromUrl(url) {
  const parsed = new URL(url);
  const wb = parsed.pathname.match(/\/catalog\/(\d+)/);
  if (wb) return `wb-${wb[1]}`;
  const slug = parsed.hostname.replace(/^www\./, "").replace(/[^a-z0-9]+/gi, "-").toLowerCase();
  return `${slug}-${hashString(url).slice(0, 10)}`;
}

function hashString(value) {
  let hash = 5381;
  for (let index = 0; index < value.length; index += 1) hash = ((hash << 5) + hash) + value.charCodeAt(index);
  return Math.abs(hash >>> 0).toString(36);
}

async function buildObservation(url, marketplace, checkedAt) {
  try {
    if (marketplace === "wildberries") return await wildberriesObservation(url, checkedAt);
    return { checked_at: checkedAt, price: null, currency: "RUB", status: "queued", message: "scheduled-update" };
  } catch (error) {
    return { checked_at: checkedAt, price: null, currency: "RUB", status: "error", message: error.message || "parse-error" };
  }
}

async function wildberriesObservation(url, checkedAt) {
  const article = new URL(url).pathname.match(/\/catalog\/(\d+)/)?.[1];
  if (!article) throw new Error("wildberries article not found");
  const endpoint = `https://card.wb.ru/cards/v4/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm=${article}`;
  const response = await fetch(endpoint, { headers: { "Accept": "application/json", "User-Agent": "price-mon-worker" } });
  if (!response.ok) throw new Error(`wildberries api ${response.status}`);
  const payload = await response.json();
  const product = payload.products?.[0] || payload.data?.products?.[0];
  if (!product) throw new Error("wildberries product not found");
  const price = extractWbPrice(product);
  if (typeof price !== "number") throw new Error("wildberries price not found");
  return {
    checked_at: checkedAt,
    price,
    currency: "RUB",
    status: "ok",
    message: "wildberries-api",
    title: product.name || product.title || null,
  };
}

function extractWbPrice(product) {
  const candidates = [];
  for (const size of product.sizes || []) {
    const price = size.price || {};
    candidates.push(price.total, price.product, price.basic, size.salePriceU, size.priceU);
  }
  candidates.push(product.salePriceU, product.priceU);
  const normalized = candidates
    .filter((value) => typeof value === "number" && value > 0)
    .map((value) => value > 100000 ? Math.round(value / 100) : value);
  return normalized.length ? Math.min(...normalized) : null;
}
