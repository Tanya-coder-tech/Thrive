import {
  amountInput, avatar, brand, btn, cardHead, dateLabel, empty, esc, icon, linkButton,
  money, pageHead, parseAmount, pill, scanPill, tile,
} from "./ui.js";
import { fundPage, openFundAction } from "./fund.js";
import { duplicatePanel } from "./duplicates.js";

const root = document.querySelector("#app");
const dialog = document.querySelector("#dialog");
const toast = document.querySelector("#toast");
const themeKey = "thrive-theme";
const themeColor = document.querySelector('meta[name="theme-color"]');
const inviteToken = new URLSearchParams(location.search).get("invite");
const state = {
  csrf: "", user: null, demo: false, groups: [], groupId: null, data: null, fund: null,
  route: "overview", expenseId: null, record: null, draft: null, result: null,
  previewError: "", editError: "", dirty: false, busy: false, authMode: "login", authError: "", pdfPage: 1,
};
let navigation = 0;
let previewTimer;
let previewSequence = 0;
let polling;
let toastTimer;

async function api(path, method = "GET", data) {
  const headers = { Accept: "application/json" };
  if (method !== "GET") headers["X-CSRF-Token"] = state.csrf;
  const form = data instanceof FormData;
  if (data !== undefined && !form) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method, headers, body: data === undefined || form ? data : JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.error || "The request failed."), { status: response.status, result });
  return result;
}

function message(text, error = false) {
  toast.textContent = text;
  toast.className = error ? "error" : "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.textContent = ""; }, 4200);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeColor.content = theme === "dark" ? "#0e1524" : "#151d32";
}

function themeSwitch() {
  const dark = document.documentElement.dataset.theme === "dark";
  return `<button type="button" class="theme-switch" data-action="toggle-theme" role="switch"
    aria-label="Dark mode" aria-checked="${dark}" title="Dark mode">
    <span class="theme-track" aria-hidden="true">${icon("sun", true)}${icon("moon", true)}</span>
  </button>`;
}

function flashError(error) { message(error.message, true); }
function updateSession(session) { state.csrf = session.csrf; state.user = session.user; }
const groupPath = suffix => `/api/groups/${state.groupId}${suffix || ""}`;
const expensePath = suffix => `/api/expenses/${state.expenseId}${suffix || ""}`;
const expenseLink = id => `#expense/${id}`;
const people = () => state.data?.members || [];
const activePeople = () => people().filter(person => !person.inactive_at);
const person = id => people().find(entry => entry.id === Number(id));
const personName = id => person(id)?.name || "Member";
const firstName = id => personName(id).split(" ")[0];
const ledger = () => state.data.ledger;
const organizer = () => state.data?.group.role === "organizer";
const pending = () => ledger().settlements.filter(payment => payment.status === "pending");

async function loadGroups(selected) {
  state.groups = (await api("/api/groups")).groups;
  const remembered = Number(sessionStorage.getItem("thrive-group"));
  state.groupId = [selected, state.groupId, remembered, state.groups[0]?.id]
    .find(id => state.groups.some(group => group.id === id)) || null;
  if (state.groupId) sessionStorage.setItem("thrive-group", String(state.groupId));
}

function go(destination) {
  const hash = "#" + destination;
  if (location.hash === hash) return route();
  location.hash = hash;
}

const sections = {
  overview: ["Overview", "grid"], expenses: ["Expenses", "receipt"], receipts: ["Receipts", "file"],
  balances: ["Balances", "wallet"], fund: ["Trip fund", "bag"], members: ["Members", "users"],
  "ai-guide": ["AI-900 & Guide", "sparkle"], settings: ["Settings", "settings"], activity: ["Activity", "activity"],
};

async function route() {
  const version = ++navigation;
  clearTimeout(polling);
  clearTimeout(previewTimer);
  previewSequence++;
  state.editError = "";
  state.previewError = "";
  state.dirty = false;
  state.result = null;
  state.record = null;
  state.draft = null;
  state.fund = null;
  state.expenseId = null;
  state.pdfPage = 1;
  if (!state.user) return renderAuth();
  const [requested, id] = location.hash.slice(1).split("/");
  state.route = requested === "expense" && /^\d+$/.test(id) ? "expense" : requested in sections ? requested : "overview";
  try {
    const group = state.groupId ? await api(groupPath()) : null;
    if (version !== navigation) return;
    state.data = group;
    if (state.route === "fund" && group) {
      const fund = await api(groupPath("/fund"));
      if (version !== navigation) return;
      state.fund = fund;
    }
    if (state.route === "expense" && group) {
      state.expenseId = Number(id);
      const record = await api(expensePath());
      if (version !== navigation) return;
      if (record.expense.group_id !== group.group.id) {
        state.groupId = record.expense.group_id;
        sessionStorage.setItem("thrive-group", String(state.groupId));
        state.data = await api(groupPath());
        if (version !== navigation) return;
      }
      setRecord(record);
    }
    render();
    if (state.draft) refreshPreview();
    scheduleScanPoll();
  } catch (error) {
    if (version !== navigation) return;
    renderError(error);
  }
}

function setRecord(record, keepDraft = false) {
  state.record = record;
  if (!keepDraft) state.draft = record.revisions.find(version => version.status === "draft") || null;
}

function renderError(error) {
  const content = `<section class="card group-empty">${empty("Couldn’t load this page", error.message, "info",
    btn("Back to overview", "go-overview", { type: "primary" }))}</section>`;
  root.innerHTML = state.user ? shell(content) : content;
}

function scheduleScanPoll() {
  if (!state.data) return;
  const processing = scan => scan === "queued" || scan === "processing";
  const watching = state.record ? processing(state.record.receipt?.scan_status) :
    state.data.expenses.some(expense => processing(expense.scan_status));
  if (!watching) return;
  const version = navigation;
  polling = setTimeout(async () => {
    if (version !== navigation) return;
    try {
      if (state.record) {
        const record = await api(expensePath());
        if (version !== navigation) return;
        const changed = record.receipt?.scan_status !== state.record.receipt?.scan_status;
        setRecord(record, state.dirty || state.busy);
        if (changed && !state.busy) {
          if (state.dirty) {
            const status = document.querySelector("#scan-notices");
            if (status) status.innerHTML = scanNotices(record.receipt);
            updateDuplicatePanel(record.receipt);
          } else {
            render();
            if (state.draft) refreshPreview();
          }
        }
      } else {
        const group = await api(groupPath());
        if (version !== navigation) return;
        const changed = group.expenses.some((entry, index) => entry.scan_status !== state.data.expenses[index]?.scan_status);
        state.data = group;
        if (changed && !dialog.open) render();
      }
      scheduleScanPoll();
    } catch (error) { if (version === navigation) flashError(error); }
  }, 1600);
}

function shell(content) {
  const activeGroup = state.data?.group ?? state.groups.find(group => group.id === state.groupId);
  const page = state.route === "expense" ? "Receipt review" : sections[state.route]?.[0] || "Overview";
  const unread = state.data?.expenses.filter(expense => expense.receipt_id && !expense.current_revision_id).length || 0;
  return `
    <div class="shell">
      <aside class="sidebar" id="sidebar" aria-label="Workspace navigation">
        ${brand()}
        <p class="side-label">WORKSPACE</p>
        <div class="group-switch">
          <button class="group-toggle" type="button" data-action="menu" data-menu="group-menu" aria-expanded="false" aria-controls="group-menu">
            <span class="group-mark">${icon("bag")}</span>
            <span class="group-label"><strong>${esc(activeGroup?.name || "Choose a group")}</strong><small>${activeGroup ? "Shared workspace" : "Group workspace"}</small></span>
            ${icon("chevron", true)}
          </button>
          <div class="dropdown" id="group-menu" hidden>
            ${state.groups.map(group => `<button type="button" data-action="switch-group" data-id="${group.id}">${icon(group.id === state.groupId ? "check" : "users", true)}${esc(group.name)}</button>`).join("")}
            ${state.groups.length ? "<hr>" : ""}<button type="button" data-action="new-group">${icon("plus", true)}New group</button>
          </div>
        </div>
        <p class="side-label">MANAGE</p>
        <nav class="navigation">${Object.entries(sections).map(([key, [label, symbol]]) => {
          const current = state.route === key || (state.route === "expense" && key === "expenses");
          const count = key === "receipts" && unread;
          return `<a href="#${key}" class="nav-link${current ? " active" : ""}" ${current ? 'aria-current="page"' : ""}
            ${count ? `aria-description="${count} receipt ${count === 1 ? "draft" : "drafts"}"` : ""}>${icon(symbol)}${label}
            ${count ? `<span class="nav-badge" aria-hidden="true">${count}</span>` : ""}</a>`;
        }).join("")}</nav>
        <div class="sidebar-footer"><button type="button" class="side-button" data-action="new-group">${icon("plus")} Create group</button></div>
      </aside>
      <button class="scrim" type="button" data-action="close-mobile" aria-label="Close navigation"></button>
      <header class="topbar">
        <div class="breadcrumbs">
          <button type="button" class="icon-button mobile-toggle" data-action="toggle-mobile" aria-label="Open navigation" aria-expanded="false" aria-controls="sidebar">${icon("menu")}</button>
          <span class="workspace-crumb">${esc(activeGroup?.name || "Workspace")}</span><span class="slash">/</span><span class="crumb-current">${page}</span>
        </div>
        <div class="top-actions">${state.demo ? '<span class="pill demo-label">Demo workspace</span>' : ""}
          ${themeSwitch()}
          <div class="profile">
            <button class="profile-button" type="button" data-action="menu" data-menu="profile-menu" aria-label="Account menu" aria-expanded="false" aria-controls="profile-menu">
              ${avatar(state.user)}<span class="profile-copy"><strong>${esc(state.user.name)}</strong><small>${esc(activeGroup?.role || "Account")}</small></span>${icon("chevron", true)}
            </button>
            <div class="dropdown" id="profile-menu" hidden>
              ${state.demo ? `<div class="dropdown-label">Switch demo member</div>${["Aman", "Simran", "Karan", "Nisha"].map(name =>
                `<button type="button" data-action="demo-person" data-person="${name.toLowerCase()}">${icon("users", true)}${name}</button>`).join("")}<hr>` : ""}
              <button type="button" data-action="sign-out">${icon("logout", true)}Sign out</button>
            </div>
          </div>
        </div>
      </header>
      <main id="main" class="main">${content}</main>
    </div>`;
}

function render() {
  if (!state.user) return renderAuth();
  if (!state.data) {
    root.innerHTML = shell(pageHead("Your workspace", "Create a group to start sharing expenses.") +
      `<section class="card group-empty">${empty("No groups yet", "Start a workspace for a trip, household, or team.", "users",
        btn("Create group", "new-group", { type: "primary", symbol: "plus" }))}</section>`);
    return;
  }
  const pages = {
    overview, expenses, receipts, balances, membersPage, activity, expense: expensePage,
    fund: () => fundPage({ fund: state.fund, organizer: organizer(), people: people() }),
    "ai-guide": aiGuidePage,
    settings: settingsPage,
  };
  root.innerHTML = shell(pages[state.route === "members" ? "membersPage" : state.route]());
}

function primaryActions() {
  return btn("Upload receipt", "upload", { symbol: "upload" }) +
    btn("New expense", "new-expense", { symbol: "plus", type: "primary" });
}

function overview() {
  const group = state.data.group;
  const net = ledger().balances.find(member => member.id === state.user.id)?.net_paise || 0;
  return pageHead("Overview", "Track shared expenses and see who owes what.", primaryActions()) + `
    <section class="hero" aria-label="Current workspace">
      <div class="hero-pattern" aria-hidden="true"></div>
      <div class="hero-copy"><span class="hero-tag">ACTIVE GROUP</span><h2>${esc(group.name)}</h2>
        ${group.description ? `<p>${esc(group.description)}</p>` : ""}</div>
      <div class="hero-balance"><p>Your balance</p><strong>${money(Math.abs(net))}</strong>
        <span>${icon(net < 0 ? "wallet" : "circle", true)}${net > 0 ? "To receive" : net < 0 ? "To pay" : "All settled"}</span>
      </div>
    </section>
    <section class="metrics" aria-label="Group summary">
      ${metric("wallet", "blue", "Total expenses", money(ledger().total_paise))}
      ${metric("users", "green", "Group members", activePeople().length)}
      ${metric("clock", "amber", "Pending payments", pending().length)}
    </section>
    <div class="dashboard-grid">
      <section class="card">${cardHead("Recent expenses", "Latest bills and receipt drafts", linkButton("View all", "#expenses"))}
        ${expenseTable(state.data.expenses.slice(0, 5))}</section>
      ${balanceCard(true)}
    </div>
    <section class="card activity-panel">${cardHead("Recent activity", "Updates across this group", linkButton("View activity", "#activity"))}
      ${activityRows(state.data.activity.slice(0, 3))}</section>`;
}

function metric(symbol, tone, label, value) {
  return `<div class="metric">${tile(symbol, tone)}<div><p>${label}</p><strong>${value}</strong></div></div>`;
}

const paymentMethods = { "": "Unspecified", cash: "Cash", upi: "UPI", bank: "Bank transfer", card: "Card", other: "Other" };
const payerName = (id, short = false) => id === null ? "Trip fund" : short ? firstName(id) : personName(id);

function payerList(contributions, short = false) {
  const payers = [...new Set(contributions.map(payment => payerName(payment.member_id, short)))];
  return short && payers.length > 2 ? `${payers[0]} + ${payers.length - 1}` : payers.join(", ");
}

function expenseTable(entries, receiptOnly = false) {
  if (!entries.length) return empty(receiptOnly ? "No receipts uploaded" : "No expenses yet",
    receiptOnly ? "Uploaded bills and their scan status will appear here." : "Add a manual expense or upload your first receipt.",
    "receipt", btn(receiptOnly ? "Upload receipt" : "New expense", receiptOnly ? "upload" : "new-expense", { symbol: receiptOnly ? "upload" : "plus" }));
  const visuals = {
    "The Campus Kitchen": ["utensils", "amber"], "Station cab": ["car", "blue"], "Morning coffee": ["coffee", "purple"],
  };
  return `<div class="table-wrap"><table class="data-table expense-table"><thead><tr><th scope="col">${receiptOnly ? "Receipt" : "Expense"}</th>
    <th scope="col" class="payer-col">Paid by</th><th scope="col">Amount</th><th scope="col">Status</th></tr></thead><tbody>
    ${entries.map(entry => {
      const label = entry.merchant || entry.draft_merchant || (entry.receipt_id ? "Receipt draft" : "Manual expense draft");
      const [symbol, color] = visuals[label] || ["receipt", "blue"];
      const status = receiptOnly ? scanPill(entry.scan_status) : entry.current_revision_id
        ? entry.draft_id ? pill("Correction", "blue") : pill("Posted", "green", "check")
        : entry.scan_status && entry.scan_status !== "ready" ? scanPill(entry.scan_status) : pill("Draft", "amber");
      return `<tr><td><a href="${expenseLink(entry.id)}" class="expense-name">${tile(symbol, color)}<span>
        <strong>${esc(label)}</strong><small>${dateLabel(entry.purchase_date || entry.draft_purchase_date || entry.created_at)}${entry.dispute_count ? " · Question open" : ""}</small></span></a></td>
        <td class="payer-col" title="${esc(payerList(entry.contributions))}">${esc(payerList(entry.contributions, true) || "—")}</td>
        <td class="amount">${money(entry.total_paise ?? entry.draft_total_paise)}</td><td>${status}</td></tr>`;
    }).join("")}</tbody></table></div>`;
}

function expenses() {
  return pageHead("Expenses", "Review draft expenses and see the bills your group has posted.", primaryActions()) +
    `<section class="card">${cardHead("All expenses", `${state.data.expenses.length} in this group`)}${expenseTable(state.data.expenses)}</section>`;
}

function receipts() {
  const uploaded = state.data.expenses.filter(expense => expense.receipt_id);
  return pageHead("Receipts", "Open the original receipt alongside its extracted details.",
    btn("Upload receipt", "upload", { type: "primary", symbol: "upload" })) +
    `<section class="card">${cardHead("Receipt uploads", `${uploaded.length} in this group`)}${expenseTable(uploaded, true)}</section>`;
}

function balanceCard(overviewMode = false) {
  const positive = ledger().transfers.length;
  return `<section class="card">${cardHead("Group balances", "Net position by member", overviewMode ? linkButton("View balances", "#balances") : "")}
    <div class="card-body">${ledger().balances.map(member => {
      const net = member.net_paise;
      const label = net > 0 ? "To receive" : net < 0 ? "To pay" : "Settled";
      const tone = net > 0 ? "positive" : net < 0 ? "negative" : "muted";
      return `<div class="balance-row">${avatar(member)}<div class="row-info"><strong>${esc(member.name)}${member.id === state.user.id ? " <small class='inline-label'>(you)</small>" : ""}</strong><small>${label}</small></div>
        <span class="amount ${tone}">${net > 0 ? "+" : net < 0 ? "−" : ""}${money(Math.abs(net))}</span></div>`;
    }).join("")}
    ${overviewMode ? `<p class="card-note">${icon("info", true)}${positive
      ? `${positive} suggested ${positive === 1 ? "transfer" : "transfers"} to settle this group.`
      : "Everyone in this group is settled."}</p>` : ""}</div></section>`;
}

function balances() {
  const transfers = ledger().transfers;
  const payments = ledger().settlements;
  const canPay = activePeople().some(member => member.id !== state.user.id);
  return pageHead("Balances", "See who owes what and confirm payments you received.",
    canPay ? btn("Record payment", "payment", { type: "primary", symbol: "payment" }) : "") +
    `<div class="two-columns">${balanceCard()}
      <section class="card">${cardHead("Suggested transfers", "Based on posted expenses and confirmed payments")}
        <div class="card-body">${transfers.length ? transfers.map(payment => `<div class="simple-row">${tile("payment")}
          <div class="row-info"><strong>${esc(firstName(payment.sender_id))} pays ${esc(firstName(payment.recipient_id))}</strong>
          <small>${money(payment.amount_paise)}</small></div>
          ${payment.sender_id === state.user.id && !payments.some(entry => entry.sender_id === payment.sender_id && entry.recipient_id === payment.recipient_id && entry.status === "pending")
            ? btn("Record", "payment", { type: "compact", attrs: `data-id="${payment.recipient_id}" data-amount="${payment.amount_paise}"` }) : ""}
        </div>`).join("") : empty("Everyone is settled", "There are no transfers to suggest.", "circle")}</div>
      </section></div>
    <section class="card closing-space">${cardHead("Payment history", "Pending payments affect balances after confirmation.")}
      ${payments.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th scope="col">Payment</th><th scope="col">Amount</th>
      <th scope="col">Status</th><th scope="col">Confirmation</th></tr></thead><tbody>
      ${payments.map(payment => `<tr><td><strong>${esc(firstName(payment.sender_id))} to ${esc(firstName(payment.recipient_id))}</strong><br>
      <small class="muted">${dateLabel(payment.created_at)}</small></td><td class="amount">${money(payment.amount_paise)}</td>
      <td>${payment.status === "confirmed" ? pill("Confirmed", "green", "check") : pill("Pending", "amber", "clock")}</td>
      <td>${payment.status === "pending" && payment.recipient_id === state.user.id
        ? btn("Confirm receipt", "confirm-payment", { type: "compact primary", attrs: `data-id="${payment.id}"` })
        : payment.status === "confirmed" ? dateLabel(payment.confirmed_at) : "Awaiting recipient"}</td></tr>`).join("")}
      </tbody></table></div>` : empty("No recorded payments", "When someone records a payment, it will appear here.", "payment")}</section>`;
}

const eventLabels = {
  group_created: ["created the group", "users"], invite_created: ["created an invitation", "link"],
  member_joined: ["joined the group", "users"], member_role_changed: ["updated a member’s role", "users"],
  draft_created: ["started an expense draft", "file"],
  draft_updated: ["saved receipt changes", "file"], receipt_uploaded: ["uploaded a receipt", "upload"],
  receipt_scanned: ["finished a receipt scan", "receipt"], expense_posted: ["posted an expense", "receipt"],
  receipt_match_reviewed: ["reviewed a receipt match", "receipt"],
  correction_proposed: ["proposed a correction", "file"], correction_approved: ["approved a correction", "check"],
  dispute_opened: ["asked a question", "message"], dispute_resolved: ["resolved a question", "check"],
  payment_recorded: ["recorded a payment", "payment"], payment_confirmed: ["confirmed a payment", "circle"],
};

function activityRows(events) {
  if (!events.length) return empty("No updates yet", "Group activity will appear as members make changes.", "activity");
  return `<div class="card-body activity-list">${events.map(event => {
    const [label, symbol] = eventLabels[event.action] || ["updated the group", "activity"];
    const detail = esc(event.detail);
    return `<div class="simple-row">${tile(symbol, symbol === "circle" ? "green" : "blue")}
      <div class="row-info"><strong>${esc(event.actor_name)} ${label}</strong><small>
      ${event.expense_id ? `<a href="${expenseLink(event.expense_id)}">${detail}</a>` : detail}</small></div>
      <time>${dateLabel(event.created_at)}</time></div>`;
  }).join("")}</div>`;
}

function activity() {
  return pageHead("Activity", "Review posted bills, payment confirmations, and changes to receipts.") +
    `<section class="card">${cardHead("Group activity")}${activityRows(state.data.activity)}</section>`;
}

function membersPage() {
  return pageHead("Members", state.data.group.name, organizer() ? btn("Invite member", "invite", { type: "primary", symbol: "plus" }) : "") +
    `<section class="card">${cardHead("Group members", `${activePeople().length} active`)}<div class="card-body">
      ${people().map(member => `<div class="simple-row">${avatar(member)}<div class="row-info"><strong>${esc(member.name)}</strong>
      <small>${member.id === state.user.id ? "You" : ""}</small></div>${pill(member.inactive_at ? "Former member" : member.role === "organizer" ? "Organizer" : "Member",
        member.role === "organizer" ? "blue" : "gray")}
      ${organizer() && !member.inactive_at ? btn("Edit role", "edit-role", { type: "compact", attrs: `data-id="${member.id}"` }) : ""}</div>`).join("")}</div></section>`;
}

function settingsPage() {
  const group = state.data.group;
  return pageHead("Settings", "Workspace rules, currency configuration, and data export") + `
    <div class="dashboard-grid">
      <section class="card">${cardHead("Group profile", "General workspace details")}
        <div class="card-body">
          <div class="selection-summary"><span>Group name</span><strong>${esc(group.name)}</strong></div>
          <div class="selection-summary"><span>Created by</span><strong>${esc(state.user.name)}</strong></div>
          <div class="selection-summary"><span>Currency</span><strong>INR (₹) · Integer Paise Engine</strong></div>
          <div class="selection-summary"><span>Reconciliation mode</span><strong>Strict Zero Drift (Largest-Remainder)</strong></div>
        </div>
      </section>
      <section class="card">${cardHead("Data export & audit", "Download accounting records")}
        <div class="card-body">
          <p style="font-size: .88rem; color: var(--muted); margin-bottom: 14px;">Export all recorded expenses, member shares, and bilateral settlement receipts.</p>
          <div class="actions">${btn("Export group data (JSON)", "export-json", { symbol: "download" })}
          <button type="button" class="side-button" onclick="window.print()">${icon("file")} Print audit report</button></div>
        </div>
      </section>
    </div>`;
}

function aiGuidePage() {
  return pageHead("AI-900 & Architecture Guide", "Visual blueprint of receipt reconciliation and Microsoft Azure AI-900 alignment") + `
    <section class="card" style="margin-bottom: 20px;">${cardHead("Reconciliation pipeline", "Azure AI Document Intelligence to integer paise ledger")}
      <div class="card-body">
        <p style="font-size: .88rem; color: var(--muted); line-height: 1.5; margin-bottom: 14px;">
          1. <strong>Capture &amp; Ingestion:</strong> Multi-format bill uploads validated with SHA-256 deduplication.<br>
          2. <strong>Azure AI Model:</strong> Prebuilt-receipt foundation model extracts layout polygons, line items, and totals.<br>
          3. <strong>Reconciliation:</strong> Arithmetic difference calculation flags missing taxes/adjustments before posting.<br>
          4. <strong>Integer Paise Engine:</strong> Zero-drift proportional allocation distributes tax/discount without rounding errors.<br>
          5. <strong>Bilateral Settlement:</strong> Minimal transfer optimization with recipient confirmation.
        </p>
      </div>
    </section>
    <section class="card">${cardHead("Microsoft Azure AI-900 curriculum alignment", "Official domain competencies")}
      <div class="card-body">
        <div class="selection-summary"><span>Domain 1: AI Workloads &amp; Considerations</span><strong>Responsible AI Principles &amp; Fairness</strong></div>
        <div class="selection-summary"><span>Domain 2: Fundamental ML Principles</span><strong>Confidence Scores &amp; Feature Extraction</strong></div>
        <div class="selection-summary"><span>Domain 3: Computer Vision Workloads</span><strong>Azure AI Document Intelligence (OCR)</strong></div>
        <div class="selection-summary"><span>Domain 4: Generative AI &amp; Decision Support</span><strong>Discrepancy Identification &amp; Reasoning</strong></div>
      </div>
    </section>`;
}

function expensePage() {
  const current = state.record.revisions.find(version => version.id === state.record.expense.current_revision_id);
  const receipt = state.record.receipt;
  const title = current?.merchant || state.draft?.merchant || (receipt ? "Receipt review" : "New expense");
  const actions = current && !state.draft ? btn("Propose correction", "correction", { symbol: "file" }) : "";
  const detail = state.draft
    ? current ? "Review proposed shares before approving the correction." : "Check the receipt details and assign each share."
    : `Paid by ${payerList(current.contributions)} · ${dateLabel(current.purchase_date)}`;
  const left = receipt ? originalPanel(receipt) : state.draft ? "" : revisionHistory(current);
  const right = state.draft ? reviewForm(current) : postedDetails(current);
  return pageHead(title, detail, actions) + `
    <div id="scan-notices">${scanNotices(receipt)}</div>
    <div id="duplicate-matches">${duplicatePanel(receipt)}</div>
    ${left ? `<div class="two-columns review-layout">${left}<div class="stack">${right}</div></div>` : `<div class="stack">${right}</div>`}
    ${current && receipt ? revisionHistory(current) : ""}
    ${current ? disputePanel(current) : ""}`;
}

function scanNotices(receipt) {
  if (!receipt) return "";
  const { scan_status: status, scan_error: error } = receipt;
  return (status === "queued" || status === "processing" ? `<p class="notice" role="status">${icon("clock", true)}
      ${status === "queued" ? "Scan queued." : "Scanning the receipt."} You can also enter the details manually.</p>` : "") +
    (status === "failed" ? `<p class="notice warning">${esc(error || "The scan failed. Enter the details manually.")}
      <button class="text-button" type="button" data-action="retry-scan">Retry scan</button></p>` : "");
}

function updateDuplicatePanel(receipt, focusId) {
  const panel = root.querySelector("#duplicate-matches");
  if (!panel) return;
  const openIds = [...panel.querySelectorAll("details[open]")].map(entry => Number(entry.dataset.matchId));
  panel.innerHTML = duplicatePanel(receipt, openIds);
  if (focusId) panel.querySelector(`[data-match-id="${focusId}"] summary`)?.focus();
}

function originalPanel(receipt) {
  const isPdf = receipt.mime_type === "application/pdf";
  const page = state.pdfPage;
  const pageUrl = receipt.pdf_preview_url?.replace(/\/1$/, `/${page}`);
  const preview = isPdf
    ? pageUrl ? `<img data-pdf-preview src="${esc(pageUrl)}" alt="Original PDF receipt, page ${page}">` :
      '<p class="muted">Open or download this PDF to view the original.</p>'
    : `<img src="${esc(receipt.preview_url)}" alt="Original receipt for ${esc(receipt.filename)}">`;
  const pageControl = receipt.page_count > 1 ? `<div class="pdf-controls">
    ${btn("Previous page", "pdf-page", { type: "compact", attrs: `data-delta="-1" ${page === 1 ? "disabled" : ""}` })}
    <span aria-live="polite">Page ${page} of ${receipt.page_count}</span>
    ${btn("Next page", "pdf-page", { type: "compact", attrs: `data-delta="1" ${page === receipt.page_count ? "disabled" : ""}` })}
    </div>` : "";
  return `<section class="card receipt-panel">${cardHead("Original receipt", "Compare with the reviewed details", scanPill(receipt.scan_status))}
    <div class="card-body"><div class="receipt-original">${preview}</div>${pageControl}<div class="receipt-meta"><small>${esc(receipt.filename)}</small>
    <div class="actions">${isPdf ? `<a class="text-button" href="${esc(receipt.preview_url)}" target="_blank" rel="noopener">Open PDF</a>` : ""}
    <a class="text-button" href="${esc(receipt.preview_url)}?download=1">Download</a></div></div>${receipt.extracted ? sourceDetails(receipt.extracted) : ""}</div></section>`;
}

function sourceDetails(source) {
  return `<details class="version"><summary>Original extracted values</summary>
    <div class="selection-summary"><span>Merchant</span><strong>${esc(source.merchant || "Missing")}</strong></div>
    <div class="selection-summary"><span>Date</span><strong>${dateLabel(source.purchase_date) || "Missing"}</strong></div>
    ${source.items.map(item => `<div class="selection-summary"><span>${esc(item.description || "Unnamed item")}</span><strong>${money(item.amount_paise)}</strong></div>`).join("")}
    ${source.adjustments.map(adj => `<div class="selection-summary"><span>${esc(adjustmentLabels[adj.kind])}</span><strong>${money(adj.amount_paise)}</strong></div>`).join("")}
    <div class="selection-summary"><span>Total</span><strong>${money(source.total_paise)}</strong></div></details>`;
}

function field(label, control, path = "", help = "") {
  return `<div class="field" ${path ? `data-field="${path}"` : ""}>
    <label class="field-control"><span>${label}</span>${control}</label>
    ${help ? `<small class="help">${help}</small>` : ""}${path ? `<small class="field-note" id="note-${path.replaceAll(".", "-")}" hidden></small>` : ""}</div>`;
}
function draftInput(path, value, type = "text", extras = "") {
  return `<input type="${type}" data-path="${path}" value="${esc(value)}" ${extras}>`;
}
const moneyInput = (path, value) => draftInput(path, typeof value === "string" ? value : amountInput(value), "text", 'inputmode="decimal" placeholder="0.00"');
const memberOptions = id => activePeople().map(member =>
  `<option value="${member.id}" ${id === member.id ? "selected" : ""}>${esc(member.name)}</option>`).join("");
function memberChecks(path, selected, label) {
  return `<div class="check-list" role="group" aria-label="${esc(label)}" data-field="${path}">
    ${activePeople().map(member => `<label class="check"><input type="checkbox" data-check="${path}"
      value="${member.id}" ${selected.includes(member.id) ? "checked" : ""}>${esc(firstName(member.id))}</label>`).join("")}
    <small class="field-note" hidden></small></div>`;
}
const adjustmentLabels = { tax: "Tax", discount: "Discount", rounding: "Rounding", other: "Other" };

function reviewForm(current) {
  const draft = state.draft;
  const organizerRequired = current || draft.contributions.some(payment => payment.member_id === null);
  const canPost = !organizerRequired || organizer();
  return `<section class="card">${cardHead(current ? "Correction draft" : "Review and split",
    current ? "The posted shares stay active until approval." : "Confirm the printed amounts and who shared the bill.",
    pill(`Draft · v${draft.version}`, "amber"))}
    <div class="card-body">
      ${!canPost ? '<p class="notice draft-banner">Save your changes for an organizer to review and approve.</p>' : ""}
      <div id="review-error" aria-live="polite">${reviewError()}</div>
      <div class="form-grid">
        ${field("Merchant", draftInput("merchant", draft.merchant, "text", 'maxlength="160" placeholder="e.g. The Campus Kitchen"'), "merchant")}
        ${field("Purchase date", draftInput("purchase_date", draft.purchase_date, "date"), "purchase_date")}
        ${field("Receipt total (₹)", moneyInput("total_paise", draft.total_paise), "total_paise")}
        ${field("Printed subtotal (₹)", moneyInput("subtotal_paise", draft.subtotal_paise), "subtotal_paise", "Optional when the receipt lists no subtotal.")}
      </div>
      <hr class="divider">
      <div class="section-heading"><h3>Payer contributions</h3>${btn("Add payer", "add-payer", { type: "compact", symbol: "plus" })}</div>
      ${draft.contributions.map(contributionEditor).join("")}
      <div id="funding-summary" aria-live="polite">${fundingSummary()}</div>
      <hr class="divider">
      <div class="section-heading"><h3>Split method</h3></div>
      <div class="segments" role="group" aria-label="Split method">
        ${[["equal", "Whole-bill equal split"], ["items", "Item-wise split"]].map(([value, name]) =>
          `<button type="button" data-action="split-mode" data-mode="${value}" class="${draft.mode === value ? "selected" : ""}"
          aria-pressed="${draft.mode === value}">${name}</button>`).join("")}
      </div>
      ${draft.mode === "equal" ? memberChecks("member_ids", draft.member_ids, "Members splitting the bill") : ""}
      <hr class="divider">
      <div class="section-heading"><h3>Receipt items</h3>${btn("Add item", "add-item", { type: "compact", symbol: "plus" })}</div>
      ${draft.items.length ? draft.items.map((item, index) => itemEditor(item, index, draft.mode)).join("") :
        '<p class="muted">Add line amounts if your receipt has an item breakdown.</p>'}
      <hr class="divider">
      <div class="section-heading"><h3>Adjustments</h3>${btn("Add adjustment", "add-adjustment", { type: "compact", symbol: "plus" })}</div>
      ${draft.adjustments.length ? draft.adjustments.map(adjustmentEditor).join("") :
        '<p class="muted">Add tax, discounts, or rounding shown on the receipt.</p>'}
      <hr class="divider">
      <div class="section-heading"><h3>Share preview</h3></div>
      <div id="share-preview" aria-live="polite">${sharePreview(current)}</div>
      <hr class="divider">
      <div class="actions review-buttons">
        ${btn("Save draft", "save-draft", { attrs: state.busy ? "disabled" : "" })}
        ${canPost ? btn(current ? "Approve correction" : "Post expense", "post-expense",
          { type: "primary", symbol: "check", attrs: state.busy ? "disabled" : "" }) : ""}
      </div>
    </div></section>`;
}

function contributionEditor(payment, index) {
  const path = `contributions.${index}`;
  const onlyPayer = state.draft.contributions.length === 1;
  const fundPayment = payment.member_id === null;
  const amount = typeof payment.amount_paise === "string" ? payment.amount_paise : amountInput(payment.amount_paise);
  const methodOptions = Object.entries(paymentMethods).map(([value, label]) =>
    `<option value="${value}" ${value === payment.method ? "selected" : ""}>${label}</option>`).join("");
  return `<div class="edit-row" role="group" aria-label="Payer contribution ${index + 1}">
    <div class="edit-row-grid contribution-grid">
      ${field("Paid by", `<select data-path="${path}.member_id">${memberOptions(payment.member_id)}
        <option value="fund" ${fundPayment ? "selected" : ""}>Trip fund</option></select>`, `${path}.member_id`)}
      ${field("Amount paid (₹)", draftInput(`${path}.amount_paise`, amount, "text",
        `inputmode="decimal" placeholder="${onlyPayer ? "Full receipt total" : "0.00"}"`), `${path}.amount_paise`)}
      ${fundPayment ? '<span class="muted contribution-fund">Group advance balance</span>' :
        field("Payment method", `<select data-path="${path}.method">${methodOptions}</select>`)}
      ${onlyPayer ? "" : `<button type="button" data-action="remove-payer" data-index="${index}" class="icon-button"
        aria-label="Remove payer ${index + 1}">${icon("trash", true)}</button>`}
    </div>
  </div>`;
}

function fundingSummary() {
  const result = state.result;
  if (!result) return "";
  const difference = result.contribution_difference_paise;
  const fundingIssue = result.issues.find(issue => issue.field === "contributions");
  if (difference) return `<p class="notice warning">${money(Math.abs(difference))}
    ${difference > 0 ? "is still unfunded." : "exceeds the receipt total."} Contributions total ${money(result.contribution_total_paise)}.</p>`;
  if (fundingIssue) return `<p class="notice warning">${esc(fundingIssue.message)}</p>`;
  if (!result.contribution_total_paise) return "";
  return `<div class="selection-summary"><span>Contributions total</span><strong class="amount">${money(result.contribution_total_paise)}</strong></div>`;
}

function contributionRows(contributions) {
  return contributions.map(payment => `<div class="selection-summary">
    <span>${esc(payerName(payment.member_id))}${payment.method ? ` <small class="muted">· ${esc(paymentMethods[payment.method])}</small>` : ""}</span>
    <strong class="amount">${money(payment.amount_paise)}</strong></div>`).join("");
}

function itemEditor(item, index, mode) {
  const path = `items.${index}`;
  return `<div class="edit-row"><div class="edit-row-grid">
    ${field("Item description", draftInput(`${path}.description`, item.description, "text", 'maxlength="180"'), `${path}.description`)}
    ${field("Line total (₹)", moneyInput(`${path}.amount_paise`, item.amount_paise), `${path}.amount_paise`)}
    <button type="button" data-action="remove-item" data-index="${index}" class="icon-button" aria-label="Remove item ${index + 1}">${icon("trash", true)}</button>
    </div>${mode === "items" ? memberChecks(`${path}.member_ids`, item.member_ids, `Participants for ${item.description || `item ${index + 1}`}`) : ""}</div>`;
}

function adjustmentEditor(adjustment, index) {
  const path = `adjustments.${index}`;
  const choices = Object.entries(adjustmentLabels).map(([value, label]) =>
    `<option value="${value}" ${value === adjustment.kind ? "selected" : ""}>${label}</option>`).join("");
  return `<div class="edit-row"><div class="edit-row-grid">
    ${field("Adjustment type", `<select data-path="${path}.kind">${choices}</select>`)}
    ${field("Amount (₹)", moneyInput(`${path}.amount_paise`, adjustment.amount_paise), `${path}.amount_paise`)}
    <button type="button" data-action="remove-adjustment" data-index="${index}" class="icon-button" aria-label="Remove adjustment ${index + 1}">${icon("trash", true)}</button></div>
    <label class="check closing-space"><input type="checkbox" data-path="${path}.included" ${adjustment.included ? "checked" : ""}>
      Already included in line prices</label>${adjustment.kind === "discount" ? ' <small class="muted">Enter discounts as negative amounts.</small>' : ""}</div>`;
}

function shareRows(shares, subtotals = {}, adjustments = {}) {
  const entries = Object.entries(shares);
  return entries.length ? entries.map(([id, share]) => `<div class="selection-summary"><div>${esc(personName(id))}
    ${adjustments[id] ? `<br><small class="muted">${money(subtotals[id])} items · ${money(adjustments[id])} adjustments</small>` : ""}</div>
    <strong class="amount">${money(share)}</strong></div>`).join("") : '<p class="muted">Select participants to see their shares.</p>';
}

function sharePreview(current) {
  const result = state.result;
  if (state.previewError) return `<p class="notice error">${esc(state.previewError)}</p>`;
  if (!result) return '<p class="muted">Calculating shares…</p>';
  const diff = result.difference_paise;
  const notice = diff ? `<p class="notice warning"><strong>${money(Math.abs(diff))}
    ${diff > 0 ? "unaccounted for" : "over the receipt total"}</strong>
    ${result.reconstructed_paise == null ? "" : ` · Reconstructed total ${money(result.reconstructed_paise)}`}</p>` : "";
  const hints = result.issues.length ? `<div class="notice warning"><strong>Complete the review before posting.</strong>
    <ul>${[...new Set(result.issues.map(issue => issue.message))].map(text => `<li>${esc(text)}</li>`).join("")}</ul></div>` :
    '<p class="notice success">Shares match the reviewed receipt total.</p>';
  const calculated = shareRows(result.shares, result.item_subtotals, result.adjustment_shares);
  const roundingNotes = [];
  if (result.rounding_recipients.length) {
    roundingNotes.push(`An extra paise goes to ${result.rounding_recipients.map(firstName).join(", ")}.`);
  }
  for (const entry of result.item_rounding || []) {
    const label = state.draft.items[entry.item_index]?.description || `Item ${entry.item_index + 1}`;
    roundingNotes.push(`${label} rounds up by one paise for ${entry.member_ids.map(firstName).join(", ")}.`);
  }
  if (result.adjustment_rounding?.length) {
    const direction = result.adjustment_paise < 0 ? "subtracts" : "adds";
    roundingNotes.push(`Adjustment rounding ${direction} one paise for ${result.adjustment_rounding.map(firstName).join(", ")}.`);
  }
  const rounding = roundingNotes.length ? `<p class="card-note">${esc(roundingNotes.join(" "))}</p>` : "";
  return notice + hints + (current
    ? `<div class="comparison"><div><h3>Posted shares</h3>${shareRows(current.shares)}</div><div><h3>Proposed shares</h3>${calculated}</div></div>`
    : calculated) + rounding;
}

function reviewError() {
  if (!state.editError) return "";
  return `<div class="notice error" role="alert">${esc(state.editError)}
    ${state.editError.includes("Reload") ? '<button type="button" class="text-button" data-action="reload-draft">Reload draft</button>' : ""}</div>`;
}

function markFields() {
  const issues = new Map(state.record.receipt?.uncertainty.map(entry => [entry.field, entry.source ?
    `Check scan: ${entry.source}` : "Check this extracted field."]) || []);
  const errors = new Set();
  for (const entry of state.result?.issues || []) {
    issues.set(entry.field, entry.message);
    errors.add(entry.field);
  }
  for (const label of document.querySelectorAll("[data-field]")) {
    const path = label.dataset.field;
    const issue = issues.get(path);
    label.classList.toggle("flag", Boolean(issue));
    const note = label.querySelector(".field-note");
    note.hidden = !issue;
    note.textContent = issue || "";
    const control = label.querySelector("[data-path]");
    if (control) {
      control.setAttribute("aria-invalid", String(errors.has(path)));
      if (issue) control.setAttribute("aria-describedby", note.id);
      else control.removeAttribute("aria-describedby");
    }
  }
}

function postedDetails(current) {
  return `<section class="card">${cardHead("Posted expense", `Version ${current.version} · Reviewed by ${current.posted_by_name || "group member"}`,
    pill("Posted", "green", "check"))}
    <div class="card-body">
    <div class="selection-summary"><span>Receipt total</span><strong class="amount">${money(current.total_paise)}</strong></div>
    ${current.items.map(item => `<div class="selection-summary"><div>${esc(item.description)}<br>
      <small class="muted">${esc(item.member_ids.map(firstName).join(", "))}</small></div><strong>${money(item.amount_paise)}</strong></div>`).join("")}
    ${current.adjustments.map(adjustment => `<div class="selection-summary"><span>${esc(adjustmentLabels[adjustment.kind])}
      ${adjustment.included ? '<small class="muted">· Included</small>' : ""}</span><strong>${money(adjustment.amount_paise)}</strong></div>`).join("")}
    <hr class="divider"><h3>Payer contributions</h3>${contributionRows(current.contributions)}
    <hr class="divider"><h3>Member shares</h3>${shareRows(current.shares)}</div></section>`;
}

function revisionHistory(current) {
  const posted = state.record.revisions.filter(version => version.status === "posted");
  return `<section class="card closing-space">${cardHead("Revision history", "Posted versions retain their original shares.")}
    <div class="card-body">${posted.map(version => `<details class="version"><summary>Version ${version.version}
      ${version.id === current.id ? " · Current" : ""} · ${money(version.total_paise)}</summary>
      <div class="selection-summary"><span>${esc(version.posted_by_name || "Group member")} approved</span><span>${dateLabel(version.posted_at)}</span></div>
      ${version.items.map(item => `<div class="selection-summary"><span>${esc(item.description)} · ${esc(item.member_ids.map(firstName).join(", "))}</span><span>${money(item.amount_paise)}</span></div>`).join("")}
      <h3>Payer contributions</h3>${contributionRows(version.contributions)}
      <h3>Member shares</h3>${shareRows(version.shares)}</details>`).join("")}</div></section>`;
}

function disputePanel(current) {
  const entries = state.record.disputes;
  return `<section class="card closing-space">${cardHead("Questions and disputes", "Discuss a line item or the full expense.",
    btn("Ask a question", "dispute", { symbol: "message", attrs: `data-id="${current.id}"` }))}
    <div class="card-body">${entries.length ? entries.map(entry => `<article class="dispute">
      <div class="section-heading"><strong>${esc(entry.actor_name)} · ${esc(entry.item_description || "Whole expense")}</strong>
      ${entry.status === "open" ? pill("Open", "amber") : pill("Resolved", "green", "check")}</div>
      <p>${esc(entry.reason)}</p><small class="muted">${dateLabel(entry.created_at)} · Version ${state.record.revisions.find(row => row.id === entry.revision_id)?.version || "—"}</small>
      ${entry.status === "resolved" ? `<p><strong>${esc(entry.resolver_name)}</strong> · ${esc(entry.resolution)}</p>` :
        organizer() ? `<div class="closing-space">${btn("Resolve question", "resolve", { type: "compact", attrs: `data-id="${entry.id}"` })}</div>` : ""}
      </article>`).join("") : empty("No open questions", "Questions about this receipt will appear here.", "message")}</div></section>`;
}

function draftPayload() {
  const draft = structuredClone(state.draft);
  const convert = value => typeof value === "string" ? parseAmount(value) : value;
  draft.total_paise = convert(draft.total_paise);
  draft.subtotal_paise = convert(draft.subtotal_paise);
  for (const entry of [...draft.contributions, ...draft.items, ...draft.adjustments]) {
    entry.amount_paise = convert(entry.amount_paise);
  }
  return { revision_id: draft.id, edit_version: draft.edit_version, draft };
}

function drawPreview() {
  const container = document.querySelector("#share-preview");
  if (!container) return;
  const current = state.record.revisions.find(version => version.id === state.record.expense.current_revision_id);
  container.innerHTML = sharePreview(current);
  root.querySelector("#funding-summary").innerHTML = fundingSummary();
  markFields();
}

async function refreshPreview() {
  const sequence = ++previewSequence;
  try {
    const result = await api(expensePath("/preview"), "POST", draftPayload());
    if (sequence !== previewSequence || !state.draft) return;
    state.result = result;
    state.previewError = "";
  } catch (error) {
    if (sequence !== previewSequence || !state.draft) return;
    state.result = null;
    state.previewError = error.message;
    if (error.status === 409) {
      state.editError = error.message;
      document.querySelector("#review-error").innerHTML = reviewError();
    }
  }
  drawPreview();
}

function markDirty(rerender = false, focus = "") {
  state.dirty = true;
  previewSequence++;
  clearTimeout(previewTimer);
  if (rerender) {
    render();
    markFields();
    if (focus) root.querySelector(focus)?.focus();
  }
  previewTimer = setTimeout(refreshPreview, 180);
}

root.addEventListener("input", event => {
  if (!state.draft || state.busy) return;
  const input = event.target;
  const path = input.dataset.path || input.dataset.check;
  if (!path) return;
  const keys = path.split(".");
  const key = keys.pop();
  const target = keys.reduce((value, part) => value[part], state.draft);
  if (input.dataset.check) {
    const id = Number(input.value);
    const members = new Set(target[key]);
    if (input.checked) members.add(id);
    else members.delete(id);
    target[key] = [...members];
  } else if (key === "member_id") {
    target.member_id = input.value === "fund" ? null : Number(input.value);
    if (target.member_id === null) target.method = "";
  } else {
    target[key] = input.type === "checkbox" ? input.checked : input.value;
  }
  if (key === "kind" || key === "member_id") markDirty(true, `[data-path="${path}"]`);
  else markDirty();
});

async function saveOrPost(post) {
  if (state.busy) return;
  const navigationAtStart = navigation;
  const path = expensePath();
  state.busy = true;
  state.editError = "";
  const buttons = root.querySelectorAll('[data-action="save-draft"], [data-action="post-expense"]');
  buttons.forEach(button => { button.disabled = true; });
  try {
    const payload = draftPayload();
    if (state.dirty) {
      const saved = await api(path + "/draft", "PATCH", payload);
      if (navigationAtStart !== navigation) return;
      state.draft.edit_version = saved.edit_version;
      payload.edit_version = saved.edit_version;
      state.dirty = false;
    }
    if (post) {
      await api(path + "/post", "POST", { revision_id: payload.revision_id, edit_version: payload.edit_version });
      if (navigationAtStart !== navigation) return;
      message(state.draft.version > 1 ? "Correction approved." : "Expense posted.");
      await route();
    } else {
      message("Draft saved.");
      await refreshPreview();
    }
  } catch (error) {
    if (navigationAtStart !== navigation) return;
    state.editError = error.message;
    if (error.result?.preview) {
      state.result = error.result.preview;
      state.previewError = "";
      drawPreview();
    }
  } finally {
    state.busy = false;
    buttons.forEach(button => { button.disabled = false; });
    if (navigationAtStart === navigation) {
      const errors = root.querySelector("#review-error");
      if (errors) errors.innerHTML = reviewError();
    }
  }
}

function renderAuth() {
  const registering = state.authMode === "register";
  root.innerHTML = `<div class="auth-screen">
    <section class="auth-branding">${brand()}<div><h1>Shared expenses, settled together.</h1>
      <p>Keep group bills, everyone’s shares, and confirmed payments in one workspace.</p></div></section>
    <main class="auth-wrapper"><section class="card">
      <header class="auth-heading"><h2>${registering ? "Create your account" : "Sign in to Thrive"}</h2>${themeSwitch()}</header>
      ${inviteToken ? '<p class="muted">Sign in to review your group invitation.</p>' : ""}
      ${state.authError ? `<p class="notice error" role="alert">${esc(state.authError)}</p>` : ""}
      <form class="form-stack" id="auth-form">
        ${registering ? field("Full name", '<input name="name" autocomplete="name" maxlength="90" required>') : ""}
        ${field("Email", '<input type="email" name="email" autocomplete="email" required>')}
        ${field("Password", `<input type="password" name="password" autocomplete="${registering ? "new-password" : "current-password"}" ${registering ? 'minlength="8"' : ""} maxlength="256" required>`)}
        <button type="submit" class="button primary">${registering ? "Create account" : "Sign in"}</button>
      </form>
      <p class="auth-switch">${registering ? "Already have an account?" : "New to Thrive?"}
        <button type="button" class="text-button" data-action="flip-auth">${registering ? "Sign in" : "Create an account"}</button></p>
      ${state.demo && !inviteToken ? '<button type="button" class="text-button" data-action="demo-person" data-person="aman">Open demo workspace</button>' : ""}
    </section></main></div>`;
}

function modal(title, contents, onSubmit, submitLabel = "Save") {
  dialog.innerHTML = `<header class="dialog-head"><h2 id="dialog-title">${esc(title)}</h2>
    <button type="button" data-action="close-dialog" class="icon-button" aria-label="Close dialog">${icon("close")}</button></header>
    <div class="dialog-content"><div class="notice error" id="dialog-error" role="alert" hidden></div>
    ${onSubmit ? `<form class="form-stack">${contents}
      <div class="dialog-actions">${btn("Cancel", "close-dialog")}<button type="submit" class="button primary">${esc(submitLabel)}</button></div>
    </form>` : contents}</div>`;
  if (!dialog.open) dialog.showModal();
  if (!onSubmit) return;
  dialog.querySelector("form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = event.submitter;
    if (button.disabled) return;
    button.disabled = true;
    const errorBox = dialog.querySelector("#dialog-error");
    errorBox.hidden = true;
    try {
      const result = await onSubmit(new FormData(event.target));
      if (result !== false) dialog.close();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    } finally { button.disabled = false; }
  });
}

function groupModal() {
  modal("Create a group", field("Group name", '<input name="name" maxlength="110" placeholder="e.g. Industrial Visit ’26" required autofocus>') +
    field("Description (optional)", '<textarea name="description" maxlength="200" placeholder="What is this group for?"></textarea>'),
  async data => {
    const response = await api("/api/groups", "POST", Object.fromEntries(data));
    await loadGroups(response.id);
    await go("overview");
    message("Group created.");
  }, "Create group");
}

function inviteModal() {
  modal("Invite a member", '<p class="muted">Create a single-use invitation that expires after seven days.</p>' +
    field("Invitee’s email (optional)", '<input type="email" name="email" placeholder="member@example.com" autofocus>'),
  async data => {
    const result = await api(groupPath("/invites"), "POST", Object.fromEntries(data));
    const link = new URL(result.path, location.origin).href;
    modal("Invitation ready", `<p>Share this link with the person you’re inviting.</p>
      <p class="invite-link"><a href="${esc(link)}" target="_blank" rel="noopener">${esc(link)}</a></p>
      <div class="dialog-actions">
      ${btn("Copy link", "copy-invite", { attrs: `data-url="${esc(link)}"`, type: "primary", symbol: "link" })}
      ${btn("Done", "close-dialog")}</div>`);
    return false;
  }, "Create invitation");
}

function editRoleModal(id) {
  const member = person(id);
  const options = ["member", "organizer"].map(role =>
    `<option value="${role}" ${member.role === role ? "selected" : ""}>${role === "member" ? "Member" : "Organizer"}</option>`).join("");
  modal(`Edit role for ${member.name}`, field("Role", `<select name="role">${options}</select>`), async data => {
    await api(groupPath(`/members/${id}`), "PATCH", Object.fromEntries(data));
    await route();
    message("Member role updated.");
  }, "Save role");
}

function invitationPrompt() {
  if (!inviteToken) return;
  modal("Join a group", `<p class="muted">Accept this invitation as ${esc(state.user.name)}.</p>`, async () => {
    const result = await api("/api/invites/accept", "POST", { token: inviteToken });
    history.replaceState(null, "", "/workspace#overview");
    await loadGroups(result.id);
    await route();
    message("You joined the group.");
  }, "Accept invitation");
}

function uploadModal() {
  const groupId = state.groupId;
  modal("Upload a receipt", `<label class="drop-zone">${icon("upload")}<strong>Choose a file or drag it here</strong>
    <small>JPG, PNG or PDF · Up to 10 MB</small><input type="file" name="receipt" accept=".jpg,.jpeg,.png,.pdf" required></label>
    ${state.demo ? `<details class="version">
      <summary>Demo receipt samples</summary>
      <ul>
        <li><a class="text-button" href="/api/demo/receipt">Original dinner receipt</a></li>
        <li><a class="text-button" href="/api/demo/receipt?sample=second-photo">Second photo of the same bill</a></li>
        <li><a class="text-button" href="/api/demo/receipt?sample=cropped-number">Photo with the receipt number cropped out</a></li>
        <li><a class="text-button" href="/api/demo/receipt?sample=separate-purchase">Separate purchase with the same total</a></li>
      </ul>
    </details>` : ""}`,
  async data => {
    const result = await api(`/api/groups/${groupId}/receipts`, "POST", data);
    go(`expense/${result.expense_id}`);
    message("Receipt uploaded.");
  }, "Upload receipt");
  const zone = dialog.querySelector(".drop-zone");
  const chooser = zone.querySelector("input");
  zone.addEventListener("dragover", event => { event.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", event => {
    event.preventDefault();
    zone.classList.remove("dragover");
    if (event.dataTransfer.files.length) chooser.files = event.dataTransfer.files;
  });
}

function paymentModal(recipient, amount) {
  const paymentKey = crypto.randomUUID();
  const options = activePeople().filter(member => member.id !== state.user.id).map(member =>
    `<option value="${member.id}" ${member.id === recipient ? "selected" : ""}>${esc(member.name)}</option>`).join("");
  modal("Record a payment", '<p class="muted">Record a payment you already sent. The recipient confirms when it arrives.</p>' +
    field("Recipient", `<select name="recipient_id" required><option value="">Select a member</option>${options}</select>`) +
    field("Amount (₹)", `<input name="amount" inputmode="decimal" placeholder="0.00" value="${amountInput(amount)}" required>`),
  async data => {
    await api(groupPath("/settlements"), "POST", { sender_id: state.user.id, recipient_id: Number(data.get("recipient_id")),
      amount_paise: parseAmount(data.get("amount")), request_key: paymentKey });
    await route();
    message("Payment recorded. Waiting for the recipient.");
  }, "Record payment");
}

function confirmPaymentModal(id) {
  const payment = ledger().settlements.find(entry => entry.id === id);
  modal("Confirm payment received", `<p class="muted">Confirm that you received <strong>${money(payment.amount_paise)}</strong>
    from <strong>${esc(personName(payment.sender_id))}</strong>.</p>`, async () => {
    await api(`/api/settlements/${id}/confirm`, "POST", {});
    await route();
    message("Payment confirmed. Balances updated.");
  }, "Confirm received");
}

function disputeModal(id) {
  const current = state.record.revisions.find(version => version.id === id);
  const options = current.items.map(item => `<option value="${item.id}">${esc(item.description)}</option>`).join("");
  modal("Ask a question", field("Receipt item", `<select name="item_id"><option value="">Whole expense</option>${options}</select>`) +
    field("What should the group review?", '<textarea name="reason" maxlength="1000" required autofocus></textarea>'),
  async data => {
    await api(expensePath("/disputes"), "POST", { revision_id: id, item_id: Number(data.get("item_id")) || null,
      reason: data.get("reason") });
    await route();
    message("Question added.");
  }, "Submit question");
}

function resolveModal(id) {
  modal("Resolve question", field("Resolution", '<textarea name="resolution" maxlength="1000" required autofocus></textarea>'),
    async data => {
      await api(`/api/disputes/${id}/resolve`, "POST", Object.fromEntries(data));
      await route();
      message("Question resolved.");
    }, "Resolve question");
}

function closeMenus(except = "") {
  for (const toggle of root.querySelectorAll("[data-menu]")) {
    if (toggle.dataset.menu === except) continue;
    toggle.setAttribute("aria-expanded", "false");
    document.getElementById(toggle.dataset.menu).hidden = true;
  }
}
function toggleMobile(open) {
  const sidebar = root.querySelector(".sidebar");
  if (!sidebar) return;
  const visible = open ?? !sidebar.classList.contains("open");
  sidebar.classList.toggle("open", visible);
  root.querySelector(".scrim").classList.toggle("open", visible);
  root.querySelector(".mobile-toggle").setAttribute("aria-expanded", String(visible));
}

const actions = {
  ...Object.fromEntries(["fund-deposit", "fund-close", "fund-refund"].map(action => [action, ({ memberId }) =>
    openFundAction(action, { fund: state.fund, memberId: Number(memberId), organizer: organizer(),
      people: people(), groupPath, api, modal, field, refresh: route, message })])),
  "toggle-theme": (_, button) => {
    const dark = button.getAttribute("aria-checked") !== "true";
    const theme = dark ? "dark" : "light";
    applyTheme(theme);
    button.setAttribute("aria-checked", String(dark));
    try {
      localStorage.setItem(themeKey, theme);
    } catch {
      // The switch still works when browser storage is unavailable.
    }
  },
  "go-overview": () => go("overview"),
  "export-json": () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(state.data, null, 2));
    const dl = document.createElement("a");
    dl.setAttribute("href", dataStr);
    dl.setAttribute("download", `thrive-export-${state.groupId}.json`);
    dl.click();
  },
  "new-group": groupModal,
  "switch-group": async ({ id }) => { await loadGroups(Number(id)); return go("overview"); },
  "new-expense": async (_, button) => {
    button.disabled = true;
    try {
      const expense = await api(groupPath("/expenses"), "POST", {});
      go(`expense/${expense.id}`);
    } finally { button.disabled = false; }
  },
  upload: uploadModal,
  invite: inviteModal,
  "edit-role": ({ id }) => editRoleModal(Number(id)),
  "close-dialog": () => dialog.close(),
  "copy-invite": async ({ url }) => { await navigator.clipboard.writeText(url); message("Invitation link copied."); },
  "flip-auth": () => {
    state.authMode = state.authMode === "login" ? "register" : "login";
    state.authError = "";
    renderAuth();
  },
  "demo-person": async ({ person }) => {
    updateSession(await api("/api/demo/session", "POST", { person }));
    await loadGroups();
    await route();
  },
  "sign-out": async () => {
    updateSession(await api("/api/auth/logout", "POST", {}));
    state.groups = [];
    state.groupId = null;
    state.data = null;
    await route();
  },
  "toggle-mobile": () => toggleMobile(),
  "close-mobile": () => toggleMobile(false),
  menu: ({ menu }, button) => {
    const flyout = document.getElementById(menu);
    const open = flyout.hidden;
    closeMenus(menu);
    flyout.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  },
  "split-mode": ({ mode }) => {
    if (state.draft.mode === mode) return;
    state.draft.mode = mode;
    if (mode === "equal" && !state.draft.member_ids.length) state.draft.member_ids = activePeople().map(member => member.id);
    markDirty(true, `[data-mode="${mode}"]`);
  },
  "add-item": () => {
    state.draft.items.push({ description: "", amount_paise: null, member_ids: [] });
    markDirty(true, `[data-path="items.${state.draft.items.length - 1}.description"]`);
  },
  "remove-item": ({ index }) => { state.draft.items.splice(Number(index), 1); markDirty(true); },
  "add-payer": () => {
    const currentPayers = state.draft.contributions.map(payment => payment.member_id);
    const payer = activePeople().find(member => !currentPayers.includes(member.id));
    const index = state.draft.contributions.length;
    state.draft.contributions.push({ member_id: payer?.id ?? state.user.id, amount_paise: null, method: "" });
    markDirty(true, `[data-path="contributions.${index}.amount_paise"]`);
  },
  "remove-payer": ({ index }) => { state.draft.contributions.splice(Number(index), 1); markDirty(true); },
  "add-adjustment": () => {
    state.draft.adjustments.push({ kind: "tax", amount_paise: null, included: false });
    markDirty(true, `[data-path="adjustments.${state.draft.adjustments.length - 1}.amount_paise"]`);
  },
  "remove-adjustment": ({ index }) => { state.draft.adjustments.splice(Number(index), 1); markDirty(true); },
  "save-draft": () => saveOrPost(false),
  "post-expense": () => saveOrPost(true),
  "reload-draft": route,
  "pdf-page": ({ delta }) => {
    const receipt = state.record.receipt;
    state.pdfPage = Math.max(1, Math.min(receipt.page_count, state.pdfPage + Number(delta)));
    root.querySelector(".receipt-panel").outerHTML = originalPanel(receipt);
    const controls = root.querySelector(".pdf-controls");
    const nextFocus = controls.querySelector(`[data-delta="${delta}"]:enabled`) || controls.querySelector("button:enabled");
    nextFocus?.focus();
  },
  "retry-scan": async () => {
    const status = await api(`/api/receipts/${state.record.receipt.id}/retry`, "POST", {});
    state.record.receipt.scan_status = status.scan_status;
    document.querySelector("#scan-notices").innerHTML = scanNotices(state.record.receipt);
    scheduleScanPoll();
  },
  "review-receipt-match": async ({ id, decision }, button) => {
    const current = state.record?.receipt;
    if (!current || state.busy) return;
    button.disabled = true;
    try {
      const receipt = await api(`/api/receipts/${current.id}/matches/${id}`, "PATCH", { decision });
      if (state.record?.receipt?.id !== current.id) return;
      state.record.receipt = receipt;
      updateDuplicatePanel(receipt, Number(id));
      message(decision === "duplicate" ? "Receipt marked as a duplicate." : "Receipt marked as a separate purchase.");
    } finally { button.disabled = false; }
  },
  correction: async () => { await api(expensePath("/corrections"), "POST", {}); await route(); },
  payment: ({ id, amount }) => paymentModal(Number(id), Number(amount)),
  "confirm-payment": ({ id }) => confirmPaymentModal(Number(id)),
  dispute: ({ id }) => disputeModal(Number(id)),
  resolve: ({ id }) => resolveModal(Number(id)),
};

document.addEventListener("click", async event => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    if (event.target.closest(".sidebar a")) toggleMobile(false);
    closeMenus();
    return;
  }
  const action = button.dataset.action;
  if (action !== "menu") closeMenus();
  if (state.busy && ["split-mode", "add-item", "remove-item", "add-adjustment", "remove-adjustment", "add-payer", "remove-payer"].includes(action)) return;
  try { await actions[action]?.(button.dataset, button); }
  catch (error) { flashError(error); }
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") { closeMenus(); toggleMobile(false); }
});
root.addEventListener("error", event => {
  const preview = event.target;
  if (!preview.matches?.("[data-pdf-preview]")) return;
  const fallback = document.createElement("p");
  fallback.className = "muted";
  fallback.textContent = "Open or download this PDF to view the original.";
  preview.replaceWith(fallback);
}, true);
root.addEventListener("submit", async event => {
  if (event.target.id !== "auth-form") return;
  event.preventDefault();
  event.submitter.disabled = true;
  try {
    updateSession(await api(`/api/auth/${state.authMode}`, "POST", Object.fromEntries(new FormData(event.target))));
    state.authError = "";
    await loadGroups();
    await route();
    invitationPrompt();
  } catch (error) {
    state.authError = error.message;
    renderAuth();
  }
});

window.addEventListener("hashchange", route);

let savedTheme;
try {
  savedTheme = localStorage.getItem(themeKey);
} catch {
  // Use the default theme when browser storage is unavailable.
}
applyTheme(savedTheme === "dark" ? "dark" : "light");

try {
  const account = await api("/api/session" + (inviteToken ? "?invite=1" : ""));
  updateSession(account);
  state.demo = account.demo;
  if (state.user) await loadGroups();
  await route();
  if (state.user) invitationPrompt();
} catch (error) {
  renderError(error);
}
