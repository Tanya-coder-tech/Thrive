import { dateLabel, esc, money } from "../ui.js";

const portraits = {
  "Aman Sharma": "avatar-aman",
  "Simran Kaur": "avatar-simran",
  "Karan Patel": "avatar-karan",
};
const paymentMethods = {
  cash: "Cash", upi: "UPI", card: "Card", bank: "Bank transfer", other: "Other",
};
const scanLabels = {
  queued: "Queued for scan", processing: "Scanning", failed: "Manual review",
};
const differenceMoney = new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", minimumFractionDigits: 0,
});
const calendarDate = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

const symbol = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const participantCount = count => `${count} ${count === 1 ? "member" : "members"}`;
const dateOnly = value => value?.match(/^\d{4}-\d{2}-\d{2}/)?.[0] || "";
const shortDate = value => dateLabel(value).replace(/ \d{4}$/, "");
const initials = name => name.trim().split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase() || "?";
const differenceLabel = amount => `${differenceMoney.format(Math.abs(amount) / 100)} difference`;

function avatar(person, demo) {
  const portrait = demo ? portraits[person.name] : "";
  return `<span class="avatar ${portrait || "avatar-initials"}" title="${esc(person.name)}">${esc(initials(person.name))}</span>`;
}

function avatarStack(people, demo) {
  const visible = people.slice(0, 3);
  const overflow = people.length - visible.length;
  return visible.map(person => avatar(person, demo)).join("") +
    (overflow ? `<span class="avatar avatar-initials">+${overflow}</span>` : "");
}

function statusBadge(review, label) {
  return review
    ? `<span class="status status-review"><span></span>${esc(label || "Needs review")}</span>`
    : `<span class="status status-settled">${symbol("check")}${esc(label || "Posted")}</span>`;
}

export function presentation(entry, group, demo) {
  const review = Boolean(entry.draft_id) || !entry.current_revision_id;
  const merchant = (review && entry.draft_merchant) || entry.merchant || "";
  const total = (review ? entry.draft_total_paise : entry.total_paise) ?? entry.total_paise;
  const date = dateOnly((review && entry.draft_purchase_date) || entry.purchase_date || entry.created_at);
  const mode = (review && entry.draft_mode) || entry.mode;
  const receipt = Boolean(entry.receipt_id);
  const split = mode === "items" ? "Item-wise split" : mode === "equal" ? "Equal split" : "";
  const scan = scanLabels[entry.scan_status] || "";
  let title = merchant || entry.receipt_filename || "Untitled expense";
  let description = scan && review ? scan : split || (receipt ? "Receipt" : "Manual expense");
  let icon = receipt ? "receipt" : "expenses";
  let category = "";
  let accent = "";
  if (demo && group?.name === "Jaipur Industrial Visit") {
    if (merchant === "The Campus Kitchen") {
      title = "Group dinner";
      description = [merchant, description].filter(Boolean).join(" · ");
      icon = "food";
      category = "Food";
      accent = "symbol-dinner";
    } else if (merchant === "Transport booking") {
      icon = "bus";
      category = "Transport";
      description = "Coach transfer for the industrial visit";
    } else if (merchant === "Refreshments") {
      icon = "cup";
      category = "Food";
      description = "Tea and snacks on the return trip";
      accent = "symbol-refreshments";
    }
  }
  return {
    ...entry, merchant, total, date, title, description, receipt, review, scan, icon, category, accent,
    status: review ? "review" : "settled",
    payments: (review ? entry.draft_contributions : entry.contributions) || [],
  };
}

function payerSummary(payments, people) {
  if (!payments.length) return "No payer recorded";
  const ids = [...new Set(payments.map(payment => payment.member_id))];
  if (ids.length === 1 && ids[0] === null) return "Paid from trip fund";
  const names = ids.slice(0, 2).map(id => id === null ? "trip fund" : people.get(id)?.name.split(" ")[0] || "a member");
  if (ids.length > 2) return `Paid by ${names.join(", ")} +${ids.length - 2}`;
  return `Paid by ${names.join(" and ")}`;
}

function expenseRow(entry, selected, people, demo) {
  const active = entry.id === selected;
  const participantIds = [...new Set(entry.participant_ids || [])];
  const participants = participantIds.map(id => people.get(id)).filter(Boolean);
  const issue = entry.review && Number.isFinite(entry.difference_paise) && entry.difference_paise !== 0;
  const detail = issue
    ? `<span class="amount">${differenceLabel(entry.difference_paise)}</span> to reconcile`
    : entry.review ? "Review and edit the draft before posting." : "View the recorded split and contributions.";
  const action = entry.review && entry.receipt ? "Review receipt" : "View expense";
  return `<article class="expense-row${active ? " is-selected" : ""}" data-expense="${entry.id}" data-status="${entry.status}">
    <button type="button" class="expense-hit" data-select="${entry.id}" aria-label="Select ${esc(entry.title)}" aria-pressed="${active}"></button>
    <div class="expense-row-top">
      <span class="expense-meta"><span class="filter-dot ${entry.review ? "all-dot" : "settled-dot"}"></span>
        <time datetime="${esc(entry.date)}">${esc(shortDate(entry.date))}</time>${entry.category ? `<span>·</span> ${esc(entry.category)}` : ""}
      </span>
      ${statusBadge(entry.review, entry.review ? entry.scan : "")}
    </div>
    <div class="expense-main">
      <span class="expense-symbol ${entry.accent}">${symbol(entry.icon)}</span>
      <div class="expense-title"><h3>${esc(entry.title)}</h3><p>${esc(entry.description)}</p></div>
      <strong class="expense-amount amount">${money(entry.total)}</strong>
    </div>
    <div class="expense-tail">
      <span>${symbol("wallet")}${esc(payerSummary(entry.payments, people))}</span>
      ${participantIds.length ? `<span class="expense-people"><span class="avatar-stack small-avatars" aria-hidden="true">${avatarStack(participants, demo)}</span>${participantCount(participantIds.length)}</span>` : ""}
    </div>
    <div class="expense-selected-details"><p>${detail}</p>
      <button class="pill-button ${entry.review ? "review-expense" : "secondary-button"}" type="button" data-action="review" data-receipt="${entry.id}">${symbol("receipt")}${action}</button>
    </div>
  </article>`;
}

function receiptThumbnail(receiptId, mime, filename, page = 1) {
  if (!Number.isSafeInteger(receiptId) || receiptId < 1) return "";
  const pdf = mime === "application/pdf" || (!mime && /\.pdf$/i.test(filename || ""));
  return pdf ? `/api/receipts/${receiptId}/pdf-preview/${page}` : `/api/receipts/${receiptId}/file`;
}

function placeReceiptCards(entries, preferred) {
  const received = entries.filter(entry => entry.receipt);
  const pending = received.filter(entry => entry.review);
  const match = pending.find(entry => entry.id === preferred) || pending.at(-1);
  const card = document.querySelector(".review-card");
  const reviewButton = card.querySelector('[data-action="review"]');
  const peek = document.querySelector(".inbox-preview");
  const preview = match || received.at(-1);
  const delta = Number.isFinite(match?.difference_paise) && match.difference_paise !== 0;
  reviewButton.hidden = !match;
  if (match) reviewButton.dataset.receipt = match.id;
  card.querySelector("p").textContent = match?.merchant || match?.receipt_filename || (match ? "Untitled receipt" : "No receipts awaiting review");
  card.querySelector(".review-card-foot").innerHTML = match
    ? `${statusBadge(true, match.scan)}<strong class="amount">${delta ? differenceLabel(match.difference_paise) : ""}</strong>`
    : statusBadge(false, "Up to date");
  document.querySelector(".inbox-card > p").textContent = pending.length
    ? `${pending.length} ${pending.length === 1 ? "receipt" : "receipts"} awaiting review`
    : received.length ? `${received.length} ${received.length === 1 ? "receipt" : "receipts"} in this group` : "No receipts yet";
  peek.disabled = !preview;
  if (!preview) {
    peek.removeAttribute("data-receipt");
    peek.setAttribute("aria-label", "Receipt inbox is empty");
    peek.innerHTML = `<span class="inbox-placeholder">${symbol("receipt")}</span>`;
    return;
  }
  const thumbnail = receiptThumbnail(preview.receipt_id, preview.receipt_mime_type, preview.receipt_filename);
  peek.dataset.receipt = preview.id;
  peek.setAttribute("aria-label", `Preview ${preview.merchant || preview.receipt_filename || "receipt"}`);
  peek.innerHTML = `<span class="paper-shadow" aria-hidden="true"></span>
    <img class="live-inbox-photo" src="${thumbnail}" alt="" loading="eager">
    <span class="inbox-placeholder" hidden>${symbol("receipt")}</span>`;
  guardImage(peek.querySelector("img"));
}

function dayRange(dates) {
  const days = new Map();
  for (const entry of dates) {
    if (entry.current_revision_id && Number.isFinite(entry.total_paise)) {
      const date = dateOnly(entry.purchase_date || entry.created_at);
      if (date) days.set(date, (days.get(date) || 0) + entry.total_paise);
    }
  }
  const recent = [...days.keys()].sort().slice(-3);
  if (recent.length < 2) return recent.map(date => [date, days.get(date)]);
  const range = (Date.parse(recent.at(-1)) - Date.parse(recent[0])) / 86400000;
  if (range > 2) return recent.map(date => [date, days.get(date)]);
  return Array.from({ length: range + 1 }, (_, index) => {
    const date = new Date(Date.parse(recent[0]) + index * 86400000).toISOString().slice(0, 10);
    return [date, days.get(date) || 0];
  });
}

function placeSpending(expenses) {
  const days = dayRange(expenses);
  const chart = document.querySelector(".spending-chart");
  const first = days[0]?.[0];
  const last = days.at(-1)?.[0];
  document.querySelector(".spending-heading > span").textContent = first === last
    ? shortDate(first)
    : first.slice(0, 7) === last.slice(0, 7)
      ? `${Number(first.slice(8))}–${shortDate(last)}`
      : `${shortDate(first)}–${shortDate(last)}`;
  document.querySelector(".spending-total").textContent = money(days.reduce((sum, [, value]) => sum + value, 0));
  chart.setAttribute("aria-label", days.length
    ? `Posted group spending. ${days.map(([date, value]) => `${dateLabel(date)}: ${money(value)}`).join(", ")}`
    : "No posted spending yet");
  const peak = Math.max(1, ...days.map(([, value]) => value));
  chart.style.setProperty("--days", String(Math.max(1, days.length)));
  chart.innerHTML = days.length ? days.map(([date, value]) => `
    <div><span class="chart-bar${value ? "" : " zero-bar"}" style="height:${value / peak * 91}%" title="${esc(dateLabel(date))} · ${money(value)}"></span>
    <span>${esc(shortDate(date))}</span></div>`).join("") : '<p>No posted expenses yet.</p>';
}

export function renderDashboard(data, account, selectedId, filter) {
  const { group, members = [], expenses = [] } = data || {};
  const demo = Boolean(account?.demo);
  const user = account?.user;
  const activeMembers = members.filter(person => !person.inactive_at);
  const directory = new Map(members.map(member => [member.id, member]));
  const entries = expenses.map(entry => presentation(entry, group, demo))
    .sort((left, right) => left.date.localeCompare(right.date) || left.id - right.id);
  const visible = entries.filter(entry => filter === "all" || entry.status === filter);
  const selection = visible.find(entry => entry.id === Number(selectedId))
    || visible.find(entry => entry.receipt && entry.review) || visible[0];
  const name = group?.name || "Your Thrive workspace";
  const space = name.indexOf(" ");
  document.title = `${name} · Thrive`;
  document.querySelector(".group-header h1").innerHTML = space === -1
    ? esc(name) : `<span>${esc(name.slice(0, space))}</span>${esc(name.slice(space))}`;
  document.querySelector("#group-summary").textContent = group
    ? `Shared expenses for ${participantCount(activeMembers.length)}.`
    : "Create a group or accept an invitation to start sharing expenses.";
  document.querySelector(".crumb-current").textContent = name;
  const date = entries.at(-1)?.date || calendarDate.format(new Date());
  const dateMark = document.querySelector(".workspace-date");
  dateMark.dateTime = date;
  dateMark.innerHTML = `${symbol("calendar")}${esc(dateLabel(date))}`;
  const groupAvatars = document.querySelector(".member-control .avatar-stack");
  groupAvatars.setAttribute("aria-label", activeMembers.map(member => member.name).join(", "));
  groupAvatars.innerHTML = avatarStack(activeMembers, demo);
  const profile = document.querySelector(".profile-button");
  if (user?.name) {
    profile.className = `avatar profile-button ${(demo && portraits[user.name]) || "avatar-initials"}`;
    profile.setAttribute("aria-label", `${user.name}’s profile`);
    profile.textContent = initials(user.name);
  }
  const invitation = document.querySelector('[data-action="add-member"]');
  invitation.hidden = !group || group.role !== "organizer";
  document.querySelector('[data-action="upload-receipt"]').disabled = !group;
  const addExpense = document.querySelector(".add-expense");
  addExpense.dataset.action = group ? "add-expense" : "create-group";
  addExpense.innerHTML = `${symbol("plus")}${group ? "Add expense" : "Create group"}`;
  document.querySelector(".notice-button").classList.toggle("has-pending", entries.some(entry => entry.review));
  for (const button of document.querySelectorAll("button[data-filter]")) {
    const active = button.dataset.filter === filter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    if (button.dataset.filter === "settled") button.innerHTML = '<span class="filter-dot settled-dot"></span>Posted';
  }

  const feed = document.querySelector(".expense-feed");
  const scroll = feed.scrollTop;
  const emptyMessage = entries.length ? "No expenses match this filter." : "No expenses yet.";
  feed.innerHTML = `${visible.map(entry => expenseRow(entry, selection?.id, directory, demo)).join("")}
    <p class="feed-empty" id="feed-empty"${visible.length ? " hidden" : ""}>${emptyMessage}</p>`;
  feed.scrollTop = scroll;
  placeReceiptCards(entries, selection?.id);
  placeSpending(expenses);
  return selection?.id ?? null;
}

function guardImage(image) {
  if (!image) return;
  const hide = () => {
    image.hidden = true;
    image.nextElementSibling.hidden = false;
  };
  image.addEventListener("error", hide, { once: true });
  if (image.complete && !image.naturalWidth) hide();
}

function facts(heading, items) {
  if (!items.length) return "";
  return `<h3>${heading}</h3><dl class="review-facts">${items.map(([label, amount]) =>
    `<div><dt>${esc(label)}</dt><dd class="amount">${money(amount)}</dd></div>`).join("")}</dl>`;
}

export function renderReceipt(record, calculation, members, page = 1) {
  const { expense, receipt, revisions = [] } = record;
  const draft = revisions.find(revision => revision.status === "draft");
  const revision = draft || revisions.find(item => item.id === expense.current_revision_id) || revisions[0];
  const people = new Map(members.map(member => [member.id, member.name]));
  const content = document.querySelector(".receipt-review-content");
  const title = document.querySelector("#receipt-review-title");
  const subtitle = document.querySelector("#receipt-review .dialog-header p");
  const difference = calculation?.difference_paise;
  const hasDifference = Number.isFinite(difference) && difference !== 0;
  const issues = calculation?.issues || [];
  const scanMessage = receipt?.scan_error || (receipt?.scan_status === "processing" || receipt?.scan_status === "queued"
    ? "Scanning is in progress. The editor will update when the scan is ready." : "");
  const pageCount = Number(receipt?.page_count) || 1;
  const currentPage = Math.max(1, Math.min(pageCount, Number(page) || 1));
  const image = receiptThumbnail(receipt?.id, receipt?.mime_type, receipt?.filename, currentPage);
  const contributions = calculation?.contributions || revision?.contributions || [];
  const shares = Object.entries(calculation?.shares || revision?.shares || {});
  const amountLines = [
    ["Scanned total", receipt?.extracted?.total_paise], ["Receipt total", revision?.total_paise],
    ["Reconstructed total", calculation?.reconstructed_paise],
  ].filter(([, amount]) => Number.isFinite(amount));
  const download = receipt && Number.isSafeInteger(receipt.id) ? `/api/receipts/${receipt.id}/file?download=1` : "";
  title.textContent = receipt && draft ? "Review receipt" : "Expense details";
  subtitle.textContent = [revision?.merchant || receipt?.filename || "Untitled expense", dateLabel(revision?.purchase_date)].filter(Boolean).join(" · ");
  content.classList.toggle("no-receipt-image", !receipt);
  content.innerHTML = `${receipt ? `<section class="original-panel live-original" aria-label="Original receipt preview">
    ${image ? `<img src="${image}" alt="${esc(receipt.filename || "Original receipt")}">
      <p class="receipt-image-fallback" hidden>Preview unavailable.</p>` : '<p>Preview unavailable.</p>'}
    ${pageCount > 1 ? `<div class="preview-navigation">
      <button type="button" class="tool-button" data-action="review-page" data-page="${currentPage - 1}" ${currentPage === 1 ? "disabled" : ""}>Previous</button>
      <span>Page ${currentPage} of ${pageCount}</span>
      <button type="button" class="tool-button" data-action="review-page" data-page="${currentPage + 1}" ${currentPage === pageCount ? "disabled" : ""}>Next</button>
    </div>` : ""}
    ${download ? `<a class="tool-button preview-download" href="${download}">Download original</a>` : ""}</section>` : ""}
    <section class="review-details" aria-label="Expense amounts and review">
      <div class="review-difference${draft ? "" : " review-posted"}">
        ${statusBadge(Boolean(draft), draft && scanLabels[receipt?.scan_status])}
        ${hasDifference ? `<strong class="amount">${differenceLabel(difference)}</strong>` : ""}
        ${scanMessage ? `<p>${esc(scanMessage)}</p>` : ""}
        ${issues.length ? `<ul class="review-issues">${issues.map(issue => `<li>${esc(issue.message)}</li>`).join("")}</ul>` : ""}
      </div>
      ${facts("Receipt totals", amountLines)}
      ${facts("Line items", (revision?.items || []).map(item => [item.description || "Untitled item", item.amount_paise]))}
      ${facts("Adjustments", (revision?.adjustments || []).map(item => [
        `${item.kind[0].toUpperCase()}${item.kind.slice(1)}${item.included ? " (included)" : ""}`, item.amount_paise,
      ]))}
      ${facts("Payer contributions", contributions.map(payment => [
        [payment.member_id === null ? "Trip fund" : people.get(payment.member_id) || "Group member", paymentMethods[payment.method]].filter(Boolean).join(" · "),
        payment.amount_paise,
      ]))}
      ${facts(draft ? "Share preview" : "Member shares", shares.map(([id, amount]) => [people.get(Number(id)) || "Group member", amount]))}
      <div class="receipt-review-actions"><button class="pill-button review-expense" type="button" data-action="edit-receipt" data-receipt="${expense.id}">${draft ? (receipt ? "Open receipt editor" : "Open expense editor") : "Open expense"}</button></div>
    </section>`;
  guardImage(content.querySelector(".live-original img"));
}
