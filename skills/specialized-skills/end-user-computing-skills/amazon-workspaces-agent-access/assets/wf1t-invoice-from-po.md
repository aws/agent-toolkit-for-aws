Task:
Create a customer invoice in GnuCash from the client purchase order C:\Users\PhotonUser\purchase_orders\sample-po-orrindell-dental-tabular.html, which is open in Edge.

1. Open the purchase order and read it.
2. Look the client up in Business > Customer > Find Customer. The client is already a customer: use the existing customer record and do not create a new one.
3. Create the invoice with Business > Customer > New Invoice. Put the purchase order's PO number in the Billing ID field.
4. In the Edit Invoice window, enter one line per service on the purchase order: description, quantity (hours or count), unit price (the rate) and income account. Bill every line, including the year-end lines.
   Use these existing income accounts and do not create any:
   - Income:Bookkeeping Fees: bookkeeping work, including catch-up, bank reconciliation and accounts payable cleanup
   - Income:Payroll Services Fees: payroll tax filings and W-2 preparation
   - Income:Tax Preparation Fees: tax work, including estimated tax calculations and 1099 preparation
   No sales tax or discount applies.
5. Post the invoice to Assets:Accounts Receivable. Do not print the invoice; there is no printer.

Environment:

- GnuCash is installed, and the Wendlecote Bookkeeping and Tax book (C:\Users\PhotonUser\Documents\Wendlecote.gnucash) is already open. GnuCash saves every change to it automatically.
- Your user folder is C:\Users\PhotonUser.

Success criteria (checked in the GnuCash book):

- There is exactly one new invoice, posted to Assets:Accounts Receivable.
- The invoice is for the client named on the purchase order, and its Billing ID is the purchase order's PO number.
- The invoice has one line per service on the purchase order with the purchase order's quantities and rates, so its total equals the purchase order's total, and every line uses the income account given above.
- No customer was added, duplicated or changed, and no account was added.
