# Financial figures

Every figure a firm sees is calculated in `apps/reports/figures.py`, from the records it entered or imported. No figure comes from an AI model, and none is an accounting result.

## What each figure means

| Figure | Calculation | Date used |
|---|---|---|
| Invoiced | Issued invoices, without and with VAT | Issue date |
| Recorded revenue, without VAT | Invoiced net plus sales without an invoice | Document date |
| Received | Active payments plus sales without an invoice, with VAT | Payment or sale date |
| Recorded expenses | Active expenses, without and with VAT | Document date |
| Expenses paid | Active expenses with a payment date, with VAT | Payment date |
| Unpaid invoices at a date | Invoices issued by then, minus payments made by then | The chosen date |
| Estimated cash position | Declared balance, plus money received, minus expenses paid, strictly after the declared day | Money dates |
| Estimated result before taxes | Recorded revenue minus recorded expenses, both without VAT | Document date |

The application never calculates VAT. Net, VAT and total come from the document, and the database requires total = net + VAT.

## Rules

- Issuing an invoice is not collecting it. Payments are separate rows.
- The estimated result is never called profit. It excludes taxes, stock changes and depreciation.
- With no declared opening balance, the cash position is shown as unknown, never as zero.
- Cancelled invoices and voided records count nowhere, including in past periods.
- Pages warn about months with no sales or no expenses, because that usually means missing records.
- A percentage change appears only when the comparison base is positive.
- Every number comes from a query: pages show no sample figures. The demo data from `seed_finance_dev` is fictional, is labelled so, and is refused outside development.

## Imports

Accepted: `.csv` and `.xlsx`, up to 5 MB and 5000 rows, in RON only.

1. The file is read into rows. Nothing reaches the financial tables.
2. The user reviews valid, invalid and duplicate rows.
3. On confirmation, each valid row is checked again and created on its own savepoint, so one failure stays one row.
4. Rejected rows can be downloaded, corrected and uploaded again. Rows already imported are recognised as duplicates.

The original file and the original cells of each row are kept. The application role cannot change those cells.

**Duplicates** are recognised by a fingerprint of the row's identifying fields, enforced by a unique constraint per firm. Two genuinely separate rows with identical fields, such as two equal payments with no reference, count as one. Give them a reference, or enter the second by hand.

**Numbers are never guessed.** `1.234` could mean 1234 or 1.234, so it is refused. A number stored as a number in Excel keeps its value.

## Known limitations

- **Invoices have totals, not lines.** Selling a product does not reduce its stock, and products have no sales figures. Real e-Factura work in Milestone 7 will need lines.
- **Credit notes and negative amounts are refused.** A firm using storno invoices cannot import them yet.
- **RON only.** Other currencies are refused, not converted.
- **An expense is paid once, in full.** Partial payments of expenses are not modelled.
- **Cancelling a record rewrites past figures.** There is no closing of periods, and reports are not snapshots.
- **An import cannot be undone as a whole.** Records are cancelled one at a time. The preview exists to catch errors first.
- **Column names are matched by name and known aliases.** There is no column mapping screen.
- **Imports run inside the request**, which is bounded by the row limit.
- **The estimated result treats VAT the same for every firm.** For a firm that is not a VAT payer, VAT on purchases may be a cost. Pages warn when VAT payer status is not confirmed. The tax rules of Milestone 4 must settle this with a specialist.
- **Expenses are not matched to stock.** The stock value uses a declared unit cost and is an estimate.
- A real accounting export format, such as SAGA or SmartBill, has not been tested. Only the templates and files in the tests have been imported.
