import { btn, cardHead, dateLabel, esc, money, pill } from "./ui.js";

function comparisonSide(heading, receipt, source) {
  const image = receipt.mime_type === "application/pdf" ? receipt.pdf_preview_url : receipt.preview_url;
  const details = [
    ["Merchant", source.merchant],
    ["Purchase date", dateLabel(source.purchase_date)],
    ["Total", source.total_paise == null ? "" : money(source.total_paise)],
    ["Receipt number", source.receipt_number],
    ["Items", source.items.join(", ")],
  ];
  return `<section class="match-original">
    <h3>${heading}</h3>
    <a class="text-button" href="${esc(receipt.preview_url)}" target="_blank" rel="noopener">${esc(receipt.filename)}</a>
    ${image ? `<img src="${esc(image)}" alt="${heading}, ${esc(receipt.filename)}" loading="lazy">` : ""}
    <dl>${details.map(([label, value]) => `<div><dt>${label}</dt><dd>${esc(value || "Unavailable")}</dd></div>`).join("")}</dl>
  </section>`;
}

function matchSummary(match) {
  if (match.decision === "duplicate") return pill("Confirmed duplicate", "amber");
  if (match.decision === "different") return pill("Separate purchase", "gray");
  return match.kind === "exact" ? pill("Exact file match", "amber") : pill("Likely match", "amber");
}

export function duplicatePanel(receipt, opened = []) {
  const matches = receipt?.duplicate_matches || [];
  if (!matches.length) return "";
  const pending = matches.some(match => !match.decision);
  return `<section class="card duplicate-review">${cardHead(
    pending ? "Possible duplicate receipts" : "Receipt match decisions",
    pending ? "Compare the originals before deciding if they are the same purchase." : "",
  )}<div class="card-body">
    ${matches.map(match => `<details class="duplicate-match" data-match-id="${match.id}" ${opened.includes(match.id) ? "open" : ""}>
      <summary><span>${esc(match.filename)}</span>${matchSummary(match)}${match.posted ? pill("Posted expense", "green") : ""}</summary>
      <div class="duplicate-evidence">${match.reasons.map(reason => pill(reason, "blue")).join("")}</div>
      <div class="duplicate-originals">
        ${comparisonSide("This receipt", receipt, receipt.comparison)}
        ${comparisonSide("Matching receipt", match, match.source)}
      </div>
      ${match.reviewer_name ? `<p class="muted duplicate-reviewer">Reviewed by ${esc(match.reviewer_name)} · ${dateLabel(match.reviewed_at)}</p>` : ""}
      <div class="actions duplicate-actions">
        <a class="button compact" href="#expense/${match.expense_id}">${match.posted ? "View posted expense" : "View receipt draft"}</a>
        ${match.decision !== "different" ? btn("Separate purchase", "review-receipt-match", {
          type: "compact", attrs: `data-id="${match.id}" data-decision="different"`,
        }) : ""}
        ${match.decision !== "duplicate" ? btn("Mark as duplicate", "review-receipt-match", {
          type: "compact primary", attrs: `data-id="${match.id}" data-decision="duplicate"`,
        }) : ""}
      </div>
    </details>`).join("")}
  </div></section>`;
}
