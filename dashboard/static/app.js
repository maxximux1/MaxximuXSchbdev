"use strict";
// All values are written with textContent (never innerHTML), so nothing from the API can run as code.

const REFRESH_MS = 30000;
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

let accessToken = "";
let symbols = "";
let timer = null;

function store(key, value) {
  try {
    if (value === undefined) return sessionStorage.getItem(key);
    sessionStorage.setItem(key, value);
  } catch (e) { /* storage unavailable: keep working from memory */ }
  return null;
}

function init() {
  // The private link looks like  /#<token>&SYM,SYM . Read it, then remove it from the address bar.
  const hash = location.hash.slice(1);
  if (hash) {
    const [token, list] = hash.split("&");
    accessToken = token;
    store("token", token);
    if (list && !store("symbols")) store("symbols", decodeURIComponent(list));
    history.replaceState(null, "", location.pathname);
  } else {
    accessToken = store("token") || "";
  }
  symbols = store("symbols") || "";
  document.getElementById("symbols").value = symbols.split(",").join(", ");
  document.getElementById("refresh").addEventListener("click", load);
  document.getElementById("save-symbols").addEventListener("click", saveSymbols);
  document.getElementById("symbols").addEventListener("keydown", (e) => { if (e.key === "Enter") saveSymbols(); });
  load();
}

function saveSymbols() {
  symbols = document.getElementById("symbols").value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean).join(",");
  store("symbols", symbols);
  load();
}

async function load() {
  clearTimeout(timer);
  const button = document.getElementById("refresh");
  button.disabled = true;
  try {
    if (!accessToken) throw new Error("Open the private link printed in your terminal when the dashboard started.");
    const response = await fetch("/api/snapshot?symbols=" + encodeURIComponent(symbols), {
      headers: { "X-Dashboard-Token": accessToken }, cache: "no-store",
    });
    if (response.status === 401) throw new Error("This page's access link is out of date. Open the link printed in your terminal.");
    if (!response.ok) throw new Error("The dashboard could not load data (error " + response.status + ").");
    render(await response.json());
  } catch (e) {
    const offline = e instanceof TypeError;
    notices([offline ? "Cannot reach the dashboard. Is it still running in your terminal?" : e.message]);
    document.getElementById("updated").textContent = "Not updated";
  } finally {
    button.disabled = false;
    timer = setTimeout(load, REFRESH_MS);
  }
}

// ---- small DOM helpers ----------------------------------------------------
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function fill(id, children) {
  const node = document.getElementById(id);
  node.replaceChildren(...children);
  return node;
}
const has = (v) => typeof v === "number" && isFinite(v);
const usd = (v) => (has(v) ? money.format(v) : "—");
const qty = (v) => (has(v) ? number.format(v) : "—");
const time = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—");
const dateTime = (iso) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");
const title = (s) => (s ? s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ") : "");

function delta(amount, percent) {
  // Direction is carried by the arrow and sign as well as the color.
  const span = el("span");
  if (!has(amount)) { span.textContent = "—"; return span; }
  span.className = amount > 0 ? "up" : amount < 0 ? "down" : "";
  const arrow = amount > 0 ? "▲ +" : amount < 0 ? "▼ −" : "";
  let text = arrow + money.format(Math.abs(amount));
  if (has(percent)) text += " (" + (percent > 0 ? "+" : percent < 0 ? "−" : "") + Math.abs(percent).toFixed(2) + "%)";
  span.textContent = text;
  return span;
}

function table(headers, rows, emptyText) {
  if (!rows.length) return el("div", "card empty", emptyText);
  const wrap = el("div", "scroll");
  const t = el("table");
  const head = el("tr");
  headers.forEach((h) => head.append(el("th", null, h)));
  t.append(head);
  rows.forEach((cells) => {
    const tr = el("tr");
    cells.forEach((cell) => {
      const td = el("td");
      td.append(cell instanceof Node ? cell : document.createTextNode(cell));
      tr.append(td);
    });
    t.append(tr);
  });
  wrap.append(t);
  return wrap;
}

function symbolCell(symbol, description) {
  const span = el("span");
  span.append(el("b", null, symbol));
  if (description) span.append(el("span", "desc", description));
  return span;
}

function duration(seconds) {
  if (!has(seconds)) return "unknown";
  if (seconds <= 0) return "expired";
  if (seconds >= 172800) return Math.floor(seconds / 86400) + " days";
  if (seconds >= 7200) return Math.floor(seconds / 3600) + " hours";
  return Math.max(1, Math.floor(seconds / 60)) + " min";
}

// ---- rendering ------------------------------------------------------------
function notices(messages, kind) {
  fill("notices", messages.map((m) => el("div", "notice" + (kind ? " " + kind : ""), m)));
}

function statusItem(level, label, value) {
  const item = el("div", "status-item");
  item.append(el("span", "dot" + (level === "good" ? "" : " " + level)), el("span", "muted", label), el("b", null, value));
  return item;
}

function render(snap) {
  const c = snap.connection || {};
  const demo = c.mode === "demo";
  const mode = document.getElementById("mode");
  mode.hidden = false;
  mode.textContent = demo ? "Demo data" : "Live";
  document.getElementById("updated").textContent = "Updated " + time(snap.generated_at);
  notices(snap.errors || []);
  if (demo && !(snap.errors || []).length) notices(["Showing made-up demo data. Start without --demo to see your own account."], "info");

  const signIn = c.refresh_seconds_left;
  fill("status", [
    statusItem(c.ok ? "good" : "critical", "Schwab connection", c.ok ? "Connected" : "Not connected"),
    statusItem(c.reauth_required ? "critical" : has(signIn) && signIn < 86400 ? "warning" : "good",
      "Sign-in expires in", c.reauth_required ? "expired, restart to sign in" : duration(signIn)),
    statusItem("good", "Access token renews in", duration(c.access_seconds_left)),
    statusItem(c.encrypted ? "good" : "warning", "Saved tokens", c.encrypted ? "Encrypted" : "Not encrypted"),
  ]);

  const accounts = snap.accounts || [];
  const orders = snap.orders || [];
  const sum = (key) => accounts.reduce((total, a) => total + (a[key] || 0), 0);
  const totalValue = sum("value");
  const dayPl = sum("day_pl");
  const positionCount = accounts.reduce((n, a) => n + a.positions.length, 0);
  const tile = (label, value, sub) => {
    const t = el("div", "tile");
    const v = el("div", "value");
    v.append(value instanceof Node ? value : document.createTextNode(value));
    t.append(el("div", "label", label), v);
    if (sub) t.append(el("div", "sub", sub));
    return t;
  };
  const previous = totalValue - dayPl;
  fill("tiles", [
    tile("Total value", accounts.length ? usd(totalValue) : "—", accounts.length + (accounts.length === 1 ? " account" : " accounts")),
    tile("Today's change", accounts.length ? delta(dayPl) : "—",
      (previous > 0 ? (dayPl >= 0 ? "+" : "−") + Math.abs((dayPl / previous) * 100).toFixed(2) + "% " : "") + "across open positions"),
    tile("Cash", accounts.length ? usd(sum("cash")) : "—"),
    tile("Positions", String(positionCount)),
    tile("Open orders", String(orders.filter((o) => o.open).length), "last " + snap.order_days + " days"),
  ]);

  fill("accounts", accounts.length ? accounts.map(accountCard) : [el("div", "card empty", "No accounts to show.")]);

  fill("quotes", [el("div", "card", null)]).firstChild.append(table(
    ["Symbol", "Last", "Change today", "Bid", "Ask", "Volume"],
    (snap.quotes || []).map((q) => q.found
      ? [symbolCell(q.symbol, q.description), usd(q.last), delta(q.change, q.change_pct), usd(q.bid), usd(q.ask), has(q.volume) ? compact.format(q.volume) : "—"]
      : [symbolCell(q.symbol, "Not found"), "—", "—", "—", "—", "—"]),
    "Add symbols above to follow their prices."));

  document.getElementById("orders-title").textContent = "Orders, last " + snap.order_days + " days";
  fill("orders", [el("div", "card", null)]).firstChild.append(table(
    ["Symbol", "Entered", "Account", "Action", "Quantity", "Filled", "Type", "Limit price", "Status"],
    orders.map((o) => [el("b", null, o.symbol), dateTime(o.entered), o.account, title(o.instruction), qty(o.quantity), qty(o.filled),
      title(o.type), usd(o.price), el("span", "pill" + (o.open ? " open" : ""), title(o.status))]),
    "No orders in the last " + snap.order_days + " days."));

  fill("markets", (snap.markets || []).length
    ? snap.markets.map((m) => statusItem(m.open_today ? "good" : "warning", title(m.name),
        m.open_today ? "Open " + time(m.start) + " – " + time(m.end) + " (your time)" : "Closed today"))
    : [el("span", "muted", "Market hours unavailable.")]);

  fill("activity", [el("div", "card", null)]).firstChild.append(table(
    ["Request", "Time", "Result", "Took"],
    (snap.activity || []).slice(0, 20).map((a) => [a.call, new Date(a.time).toLocaleTimeString(),
      el("span", a.ok ? "" : "down", (a.ok ? "✓ " : "✕ ") + a.result), a.ms + " ms"]),
    "No requests yet."));
}

function accountCard(account) {
  const card = el("div", "card");
  const head = el("div", "card-head");
  const name = el("span");
  name.append(el("b", null, (title(account.type) || "Account") + " " + account.label));
  const totals = el("span", "muted", usd(account.value) + " total · " + usd(account.cash) + " cash");
  head.append(name, totals);
  const invested = account.positions.reduce((total, p) => total + Math.abs(p.market_value || 0), 0);
  card.append(head, table(
    ["Symbol", "Quantity", "Average cost", "Market value", "Share of holdings", "Today", "Total gain"],
    account.positions.map((p) => {
      const share = invested > 0 ? (Math.abs(p.market_value || 0) / invested) * 100 : 0;
      const cell = el("span", "share");
      const bar = el("span", "bar");
      const inner = el("i");
      inner.style.width = share.toFixed(1) + "%";
      bar.append(inner);
      cell.title = p.symbol + " is " + share.toFixed(1) + "% of this account's holdings (" + usd(p.market_value) + ")";
      cell.append(bar, document.createTextNode(share.toFixed(1) + "%"));
      return [symbolCell(p.symbol, p.description), qty(p.quantity), usd(p.average_price), usd(p.market_value), cell,
        delta(p.day_pl, p.day_pl_pct), delta(p.open_pl)];
    }),
    "No positions in this account."));
  return card;
}

init();
