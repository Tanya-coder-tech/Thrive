const paths = {
  logo: '<path d="M4 15.5 9 10l4 3.5L20 6.5M15.5 6.5H20V11"/><path d="M5 20h14"/>',
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.3"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.3"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.3"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.3"/>',
  receipt: '<path d="M6 3h12a1 1 0 0 1 1 1v17l-3-2-4 2-4-2-3 2V4a1 1 0 0 1 1-1Z"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/>',
  wallet: '<path d="M20 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/><path d="M4 8h15a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-3a2 2 0 0 1 0-4h5m-5 2h.01"/>',
  users: '<path d="M15 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2m18 0v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/><circle cx="9" cy="7" r="4"/>',
  activity: '<path d="M3 13h4l3-7 4 12 3-7h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  upload: '<path d="M12 16V4m-4 4 4-4 4 4M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  download: '<path d="M12 4v12m-4-4 4 4 4-4M4 17v3h16v-3"/>',
  bag: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18m-11 0v2h4v-2"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5l3 1.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5"/>',
  moon: '<path d="M20.8 14A8.9 8.9 0 0 1 10 3.2 9 9 0 1 0 20.8 14Z"/>',
  check: '<path d="m5 12 4 4 10-10"/>',
  circle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',
  utensils: '<path d="M5 3v5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2V3M8 3v18m10 0V3c-2 2-3 5-3 8v2h3"/>',
  car: '<path d="m5 10 1.5-4A2 2 0 0 1 8.3 5h7.4a2 2 0 0 1 1.8 1l1.5 4M4 17v2m16-2v2"/><rect x="3" y="10" width="18" height="7" rx="2"/><path d="M6.5 13.5h1m9 0h1"/>',
  coffee: '<path d="M4 8h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8Zm13 1h2a2 2 0 0 1 0 4h-2M3 21h17M7 3v2m4-2v2m4-2v2"/>',
  payment: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18m-14 5h3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
  message: '<path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l1.5-3A7.5 7.5 0 1 1 20 11.5Z"/><path d="M9 11.5h7"/>',
  logout: '<path d="M11 5H5v14h6m4-11 4 4-4 4m-6-4h10"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  file: '<path d="M13 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9l-6-6Zm0 0v6h6M9 14h6m-6 3h6"/>',
  trash: '<path d="M4 7h16M6 7l1 14h10l1-14M9 7V4h6v3m-5 4v6m4-6v6"/>',
  link: '<path d="m10 13 4-4m-6 6-1 1a3 3 0 0 1-4-4l3-3a3 3 0 0 1 4 0m4 6a3 3 0 0 0 4 0l3-3a3 3 0 0 0-4-4l-1 1"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M4.7 10a7.5 7.5 0 0 1 1-2.3l-1-1.8 1.2-1.2 1.8 1a7.5 7.5 0 0 1 2.3-1l.6-2h1.8l.6 2a7.5 7.5 0 0 1 2.3 1l1.8-1 1.2 1.2-1 1.8a7.5 7.5 0 0 1 1 2.3l2 .6v1.8l-2 .6a7.5 7.5 0 0 1-1 2.3l1 1.8-1.2 1.2-1.8-1a7.5 7.5 0 0 1-2.3 1l-.6 2h-1.8l-.6-2a7.5 7.5 0 0 1-2.3-1l-1.8 1-1.2-1.2 1-1.8a7.5 7.5 0 0 1-1-2.3l-2-.6v-1.8Z"/>',
  sparkle: '<path d="m12 3 1.9 5.5a2 2 0 0 0 1.3 1.3L20.7 12l-5.5 1.9a2 2 0 0 0-1.3 1.3L12 20.7l-1.9-5.5a2 2 0 0 0-1.3-1.3L3.3 12l5.5-1.9a2 2 0 0 0 1.3-1.3Z"/>',
};

export const icon = (name, small = false) => `<svg class="icon${small ? " small" : ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
export const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const moneyFormat = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
export const money = paise => Number.isFinite(paise) ? moneyFormat.format(paise / 100) : "—";
export const amountInput = paise => Number.isFinite(paise) ? (paise / 100).toFixed(2) : "";
export function parseAmount(value) {
  const plain = String(value).trim();
  if (!plain) return null;
  if (!/^-?(?:\d+(?:\.\d{0,2})?|\.\d{1,2})$/.test(plain)) {
    throw new Error("Enter an amount with up to two decimal places.");
  }
  const negative = plain.startsWith("-");
  const [rupees, fraction = ""] = plain.replace(/^-/, "").split(".");
  return (negative ? -1 : 1) * (Number(rupees) * 100 + Number(fraction.padEnd(2, "0")));
}
const dateFormat = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
export function dateLabel(value) {
  if (!value) return "";
  const parsed = new Date(value.includes(" ") ? value.replace(" ", "T") + "Z" : value);
  return Number.isNaN(parsed.getTime()) ? "" : dateFormat.format(parsed);
}
export const avatar = person => {
  const initials = (person?.name || "?").split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();
  return `<span class="avatar color-${(person?.id || 0) % 4}" aria-hidden="true">${esc(initials)}</span>`;
};
export const tile = (name, tone = "blue") => `<span class="tile-icon ${tone}">${icon(name)}</span>`;
export const pill = (label, tone = "gray", symbol = "") => `<span class="pill ${tone}">${symbol ? icon(symbol, true) : ""}${esc(label)}</span>`;
export const btn = (label, action, { symbol = "", type = "", attrs = "" } = {}) =>
  `<button type="button" class="button ${type}" data-action="${action}" ${attrs}>${symbol ? icon(symbol, true) : ""}${esc(label)}</button>`;
export const linkButton = (label, href) => `<a class="text-button" href="${href}">${esc(label)}</a>`;
export const brand = () => `<a class="brand" href="/" aria-label="Thrive Home"><span class="logo">${icon("logo")}</span>Thrive</a>`;
export const empty = (title, description, symbol = "receipt", action = "") =>
  `<div class="empty">${tile(symbol)}<strong>${esc(title)}</strong><p>${esc(description)}</p>${action}</div>`;
export const cardHead = (title, description = "", action = "") =>
  `<header class="card-head"><div><h2>${esc(title)}</h2>${description ? `<p>${esc(description)}</p>` : ""}</div>${action}</header>`;
export const pageHead = (title, description = "", actions = "") =>
  `<header class="page-head"><div><h1>${esc(title)}</h1>${description ? `<p>${esc(description)}</p>` : ""}</div>${actions ? `<div class="actions">${actions}</div>` : ""}</header>`;
export const scanPill = status => ({
  queued: pill("Queued", "blue", "clock"), processing: pill("Scanning", "blue", "clock"),
  ready: pill("Scan ready", "green", "check"), failed: pill("Review manually", "amber"),
})[status] || "";
