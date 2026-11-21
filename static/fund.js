import { amountInput, avatar, btn, cardHead, dateLabel, empty, esc, icon, money, pageHead, parseAmount, pill, tile } from "./ui.js";

const statuses = {
  open: ["Open", "blue"],
  refunding: ["Refunds in progress", "amber"],
  closed: ["Closed", "green"],
};

function fundSummary(fund) {
  const [label, tone] = statuses[fund.status];
  const amounts = [
    ["Advances collected", fund.deposits_paise],
    ["Paid from fund", fund.spent_paise],
    ["Refunds paid", fund.refunds_paise],
  ];
  const spentPercent = fund.deposits_paise ? fund.spent_paise / fund.deposits_paise * 100 : 0;
  const refundedPercent = fund.deposits_paise ? fund.refunds_paise / fund.deposits_paise * 100 : 0;
  return `<section class="card fund-summary" aria-label="Fund summary">
    <div class="fund-summary-top">${tile("wallet")}
      <div class="fund-cash"><h2>Available cash</h2><strong class="amount">${money(fund.available_paise)}</strong></div>
      ${pill(label, tone, fund.status === "closed" ? "check" : "")}
    </div>
    ${fund.deposits_paise ? `<div class="fund-meter" aria-hidden="true"><span class="fund-meter-spent" style="width:${spentPercent}%"></span>
      <span class="fund-meter-refunded" style="width:${refundedPercent}%"></span></div>` : ""}
    <dl class="fund-totals">${amounts.map(([label, amount]) =>
      `<div><dt>${label}</dt><dd class="amount">${money(amount)}</dd></div>`).join("")}</dl>
  </section>`;
}

function closeNotice(fund, topups) {
  if (fund.status === "open" && topups) {
    return `<p class="notice warning">${icon("info", true)} Collect ${money(topups)} in outstanding advances before beginning refunds.</p>`;
  }
  if (fund.status === "refunding") {
    return '<p class="notice">Record each refund after sending it. The fund closes automatically once all refunds are paid.</p>';
  }
  return "";
}

function positionBalance(position, status) {
  if (position.owed_paise) return `<span class="negative"><strong>${money(position.owed_paise)}</strong><small>Owes fund</small></span>`;
  if (position.refund_due_paise) {
    return `<span class="positive"><strong>${money(position.refund_due_paise)}</strong>
      <small>${status === "open" ? "Unused advance" : "Refund due"}</small></span>`;
  }
  return '<span class="muted">Settled</span>';
}

function positionRows(status, rows, hasActions) {
  const amountCell = (label, value) => `<td><span class="fund-mobile-label" aria-hidden="true">${label}</span>
    <span class="amount">${money(value)}</span></td>`;
  return rows.map(({ position, action }) => `<tr role="row">
      <th scope="row" role="rowheader" class="fund-member-cell"><span>${avatar({ id: position.member_id, name: position.name })}
        <strong>${esc(position.name)}</strong></span></th>
      ${amountCell("Advance paid", position.advance_paise)}
      ${amountCell("Actual share", position.actual_share_paise)}
      ${amountCell("Fund share", position.fund_share_paise)}
      ${amountCell("Refund paid", position.refunds_paise)}
      <td class="fund-position-cell"><span class="fund-mobile-label" aria-hidden="true">Fund balance</span>
        ${positionBalance(position, status)}</td>
      ${hasActions ? `<td class="fund-record-cell">${action}</td>` : ""}
    </tr>`).join("");
}

function memberPositions(fund, organizer, people) {
  const activeIds = new Set(people.filter(person => !person.inactive_at).map(person => person.id));
  const rows = fund.positions.map(position => {
    let action = "";
    const attrs = `data-member-id="${position.member_id}"`;
    if (organizer && fund.status === "refunding" && position.refund_due_paise > 0) {
      action = btn("Record refund", "fund-refund", { type: "compact", attrs });
    } else if (organizer && fund.status === "open" && position.owed_paise > 0 && activeIds.has(position.member_id)) {
      action = btn("Record top-up", "fund-deposit", { type: "compact", attrs });
    }
    return { position, action };
  });
  const hasActions = rows.some(row => row.action);
  return `<section class="card">
    ${cardHead("Member positions", "Actual shares include all posted expenses. Fund shares show the part covered by advances.")}
    <div class="table-wrap"><table class="data-table fund-table" role="table">
      <thead role="rowgroup"><tr role="row"><th scope="col">Member</th><th scope="col">Advance paid</th><th scope="col">Actual share</th>
        <th scope="col">Fund share</th><th scope="col">Refund paid</th><th scope="col">Fund balance</th>
        ${hasActions ? '<th scope="col">Action</th>' : ""}</tr></thead>
      <tbody role="rowgroup">${positionRows(fund.status, rows, hasActions)}</tbody>
    </table></div>
  </section>`;
}

function fundActivity(fund, people) {
  const names = new Map(people.map(person => [person.id, person.name]));
  const rows = fund.activity.map(entry => {
    const member = entry.member_name || names.get(entry.member_id) || "Member";
    const actor = names.get(entry.actor_id);
    const deposit = entry.kind === "deposit";
    const refund = entry.kind === "refund";
    const symbol = deposit ? "plus" : refund ? "payment" : "receipt";
    const title = deposit ? `Advance from ${member}` : refund ? `Refund to ${member}` : entry.description || "Fund-funded expense";
    const description = entry.expense_id ? "Expense paid from fund" : actor ? `Recorded by ${actor}` : "";
    return `<div class="simple-row fund-history-row">
      ${tile(symbol, deposit ? "green" : "blue")}
      <div class="row-info"><strong>${entry.expense_id ? `<a href="#expense/${entry.expense_id}">${esc(title)}</a>` : esc(title)}</strong>
        ${description ? `<small>${esc(description)}</small>` : ""}</div>
      <div class="fund-history-amount">
        <span class="amount${deposit ? " positive" : ""}">${deposit ? "+" : "−"}${money(entry.amount_paise)}</span>
        <time>${dateLabel(entry.created_at)}</time>
      </div>
    </div>`;
  }).join("");
  return `<section class="card">${cardHead("Fund activity")}
    ${rows ? `<div class="card-body activity-list">${rows}</div>` :
      empty("No fund activity", "Collected advances, fund-paid expenses, and refunds will appear here.", "wallet")}</section>`;
}

export function fundPage({ fund, organizer, people }) {
  const topups = fund.positions.reduce((total, position) => total + position.owed_paise, 0);
  const canCollect = organizer && fund.status === "open" && people.some(person => !person.inactive_at);
  const advances = canCollect ? btn("Record advance", "fund-deposit", { type: "primary", symbol: "plus" }) : "";
  const close = organizer && fund.status === "open" && fund.activity.length && !topups ?
    btn(fund.available_paise ? "Begin refunds" : "Close fund", "fund-close") : "";
  return pageHead("Trip fund", "Track advances, expenses paid from the fund, and refunds.", close + advances) +
    `<div class="stack">
      ${fundSummary(fund)}
      ${closeNotice(fund, topups)}
      ${fund.positions.length ? memberPositions(fund, organizer, people) : ""}
      ${fundActivity(fund, people)}
    </div>`;
}

function entryAmount(value) {
  const amount = parseAmount(value);
  if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error("Enter an amount greater than zero.");
  return amount;
}

export function openFundAction(action, { fund, memberId, organizer, people, groupPath, api, modal, field, refresh, message }) {
  if (!organizer) return;
  if (action === "fund-close" && fund.status === "open") {
    const hasRefunds = fund.available_paise > 0;
    const label = hasRefunds ? "Begin refunds" : "Close fund";
    const description = hasRefunds
      ? `<p>Make ${money(fund.available_paise)} available for refunds. This ends advance collection and spending from the fund.</p>`
      : "<p>The fund balance is zero. Closing the fund ends advance collection and spending from it.</p>";
    modal(label, description, async () => {
      await api(groupPath("/fund/begin-refunds"), "POST", {});
      await refresh();
      message(hasRefunds ? "Refunds are ready to record." : "Trip fund closed.");
    }, label);
    return;
  }

  const refund = action === "fund-refund";
  if (refund ? fund.status !== "refunding" : action !== "fund-deposit" || fund.status !== "open") return;
  const position = fund.positions.find(entry => entry.member_id === memberId);
  if (refund && !position?.refund_due_paise) return;

  const topup = !refund && (position?.owed_paise ?? 0) > 0;
  const label = refund ? "Record refund" : topup ? "Record top-up" : "Record advance";
  const help = refund ? `Record a payment already sent to ${esc(position.name)}. Up to ${money(position.refund_due_paise)} is due.`
    : "Record money already collected from a member for this trip.";
  const options = people.filter(person => !person.inactive_at).map(person =>
    `<option value="${person.id}"${person.id === memberId ? " selected" : ""}>${esc(person.name)}</option>`).join("");
  const member = refund ? "" : field("Member", `<select name="member_id" required><option value="">Select a member</option>${options}</select>`);
  const defaultAmount = refund ? position.refund_due_paise : topup ? position.owed_paise : null;
  const amount = field("Amount (₹)", `<input name="amount" inputmode="decimal" placeholder="0.00" value="${amountInput(defaultAmount)}" required>`);
  const requestKey = crypto.randomUUID();

  modal(label, `<p class="muted">${help}</p>${member}${amount}`, async data => {
    const amountPaise = entryAmount(data.get("amount"));
    if (refund && amountPaise > position.refund_due_paise) throw new Error("Enter a refund no larger than the amount due.");
    await api(groupPath("/fund/entries"), "POST", {
      kind: refund ? "refund" : "deposit",
      member_id: refund ? memberId : Number(data.get("member_id")),
      amount_paise: amountPaise,
      request_key: requestKey,
    });
    await refresh();
    message(refund ? "Refund recorded." : topup ? "Top-up recorded." : "Advance recorded.");
  }, label);
}
