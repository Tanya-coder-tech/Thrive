# Thrive Shared Expense & Receipt Reconciliation Portal

Thrive turns a group receipt into reviewed member shares and a ledger of confirmed payments. It supports INR, multiple payer contributions per expense, trip advances and refunds, and manual payment recording.

## Run locally

Use Python 3.11 or later. From this directory, install the runtime requirements and start the demo.

```powershell
python -m pip install -r requirements.txt
python app.py --demo
```

Open [Thrive on localhost](http://127.0.0.1:5050) for the Jaipur Industrial Visit opening view. You can also open `static/jaipur/index.html` directly. The opening view uses sample data and runs without a server.

The [ledger workspace](http://127.0.0.1:5050/workspace) opens as Aman Sharma in demo mode and uses fictional data in `instance/demo`. Run `python app.py` for a separate workspace with account registration. Use `--port 5051` if port 5050 is taken.

## Deploy on Render

The root `render.yaml` defines a Render Blueprint for the Flask app. In Render, choose **New + → Blueprint**, connect this GitHub repository, and deploy the Blueprint. It configures a Singapore web service with HTTPS cookies, a generated session secret, a single receipt worker, and a persistent disk for the SQLite database and uploaded receipts. The disk and web service use paid Render resources.

To enable Azure receipt scanning, set `DOCUMENTINTELLIGENCE_ENDPOINT` and `DOCUMENTINTELLIGENCE_API_KEY` in the Render service's environment. Without them, users can still enter receipt details manually.

### Opening view artwork

The built-in ImageGen tool created the fictional member portraits in `static/jaipur/member-portraits.png`.

> Create a single landscape photographic avatar contact sheet for a college-trip finance dashboard. Three equal-width adjacent portrait panels, with each face centered precisely in its panel at the same height, eyes slightly above the vertical midpoint. Left: fictional Indian male college student age 21, short wavy dark hair, navy shirt, warm tan blurred background. Center: fictional Indian female college student age 21, long dark hair, muted green shirt, softly blurred sage background. Right: fictional Indian male college student age 21, tidy cropped dark hair, russet shirt, warm muted rose background. Friendly relaxed expressions, natural editorial photography with believable skin and flattering daylight. Draw no borders or gaps between panels. Each face should remain readable in a circular profile crop centered at 50% height. No lettering, grids, logos or overlay graphics.

## Three-person demo

1. Open **The Campus Kitchen** under **Recent expenses**. The ₹840 receipt has pizza for Aman and Simran, thali for Karan, and drinks for all three. The ₹40 tax is allocated proportionally. Aman and Simran each have a ₹262.50 share and Karan has a ₹315.00 share.
2. Open the **Account menu**, switch to **Simran**, and select **Balances**. Record the ₹262.50 suggested transfer to Aman. The payment appears as pending.
3. Switch back to **Aman**. Confirm receipt of the payment. Simran’s balance is now zero and Aman has ₹315.00 to receive from Karan.
4. Reopen the expense, ask a question about **Drinks**, and propose a correction. Remove Karan from the drinks assignment. Compare the proposed shares with the posted shares. As Aman, approve the correction and resolve the question. Revision history and the confirmed payment remain visible.
5. To demonstrate receipt processing, download the sample from the **Upload receipt** dialog and upload it. The demo worker fills the new draft from a saved extraction response. The existing sample triggers a duplicate warning. Assign the items and remove the tax adjustment to expose the ₹40.00 difference, then add the tax back. Use a separate group if you also want to post the new draft.

## Jaipur trip demo

1. Select **Jaipur Trip** in the workspace picker and open **Trip fund**. Aman, Simran, Karan, and Nisha each advanced ₹1,000. The ₹3,200 coach expense leaves ₹800 in the fund and allocates ₹800 of transport to each member.
2. Open **The Campus Kitchen** under **Expenses**. Aman contributed ₹500 in cash and Simran paid ₹340 by UPI. The member shares are ₹262.50, ₹262.50, and ₹315.00. The separate personal balances are +₹237.50 for Aman, +₹77.50 for Simran, and −₹315.00 for Karan.
3. Return to **Trip fund**. As Aman, select **Begin refunds** and confirm. Record a ₹200 refund for each member. The fund closes automatically after the last refund. The dinner balances remain on **Balances**.

On a new expense, **Add payer** lets you enter each amount and payment method. A sole payer can leave its amount blank to cover the bill total. An organizer can post a **Trip fund** contribution, including a bill partially paid from personal money. Thrive allocates the fund-paid portion proportionally across the assigned shares and uses the remaining shares for personal settlements.

## Rehearse duplicate review

In **Industrial Visit ’26**, open **Upload receipt** and expand **Demo receipt samples**. Upload **Second photo of the same bill** to compare it with the seeded dinner receipt. The **Possible duplicate receipts** section explains the match and shows both originals. A reviewer can mark the new upload as a duplicate or as a separate purchase. Confirming a duplicate blocks a second ledger posting when its counterpart is already posted.

The matching tests compare saved extraction responses in three isolated pairs.

| Pair | Expected classification | Detector result |
| --- | --- | --- |
| Original versus a different photo of the same receipt | Duplicate | Flagged |
| Original versus a separate purchase with the same merchant, date, and total | Separate purchase | Unflagged because the printed numbers differ |
| Original versus a cropped photo with no receipt number | Duplicate | Flagged with item corroboration |

The fixtures detected 2 of 2 duplicates and flagged 0 of 1 separate purchases. This measures the matching rules on synthetic photos with saved extraction fields. Real-world accuracy depends on the OCR and needs evaluation on labeled photos.

## Runtime and storage

- Flask serves the UI and API. SQLite stores group memberships, versioned payer contributions, posted shares, trip fund transactions, duplicate decisions, and audit events. Existing single-payer expenses migrate to a contribution from the original payer.
- Receipt originals are written under `instance/` and served through group-authorized routes. Uploads accept up to 10 MB of JPEG, PNG, or PDF. PDFium renders private page images for side-by-side review. The queue persists in SQLite, and expired job leases can be reclaimed.
- `reconciliation.py` validates totals and calculates shares in integer paise. `ledger.py` projects balances from the current posted revision and confirmed settlements. `receipt_extraction.py` normalizes the model response and retains the extracted values for review.
- Running `python app.py` starts the web process and receipt worker together. With a WSGI host, use `app:create_app()` and run `flask --app app worker` against the same writable instance directory. For HTTPS, configure `THRIVE_SECRET_KEY` and `THRIVE_HTTPS=1`.

### Azure receipt scanning

Set `DOCUMENTINTELLIGENCE_ENDPOINT` and `DOCUMENTINTELLIGENCE_API_KEY` in the backend environment and restart the server and worker. Thrive sends originals to the Azure Document Intelligence `prebuilt-receipt` model. When credentials are absent or scanning fails, the reviewer can retry or complete the draft manually. The supplied demo receipt always uses the saved response in demo mode. [Microsoft’s streaming REST API](https://learn.microsoft.com/en-us/rest/api/aiservices/document-models/analyze-document-from-stream?view=rest-aiservices-v4.0%2B%282024-11-30%29)

## Verification

```powershell
python -m unittest discover -s tests -v
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python tests/jaipur_browser.py
python tests/browser_smoke.py
python evaluate_extraction.py fixtures/evaluation.jsonl
```

The acceptance test uploads the ₹840 receipt into a fresh group, scans the saved response, reconciles the tax, and checks the three shares and ledger. It exercises stale saves, simultaneous retries of Post and Confirm, unauthorized file access, and correction after payment. The split tests check 400 randomized allocations for rounding and exact totals. The browser smoke test runs the workflow in an isolated database and checks the mobile layout.

### Extraction evaluation

| Dataset | Receipts | Merchant | Date | Total | Matched line amounts | Flagged for review |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fictional Thrive dinner fixture | 1 | 1/1 | 1/1 | 1/1 | 3/3 | 0/1 |

These figures exercise normalization with a saved response. Live Azure and public dataset accuracy remain unmeasured.

For a labeled corpus, provide a JSON Lines manifest in the format of `fixtures/evaluation.jsonl`. Each row names a dataset, a saved response file relative to the manifest, and its expected fields. Use ISO dates and integer hundredths of the printed currency. For offline evaluation, a row can declare its printed currency, such as `"currency":"IDR"` for CORD. The portal still accepts INR expenses. The evaluator reports coverage separately from amount accuracy for matched descriptions. Its manual-review count marks mismatches, failed scans, and low-confidence fields.

For the AI-900 project report, describe OCR and structured extraction in the receipt review, human verification alongside the original, and who posted or approved each revision. Use public receipt labels for extraction evaluation and retain the separate ledger invariants for financial correctness. [CORD by NAVER CLOVA](https://github.com/clovaai/cord)
