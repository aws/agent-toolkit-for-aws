Task:
Review a client refund request and apply a credit in GnuCash.

1. Open C:\Users\PhotonUser\sample-refund-requests.csv and read the request. Work out the customer (match the sender's email address or phone number to a GnuCash customer), the invoice it is about, the amount claimed and the reason given.
2. Look the invoice up with Business > Customer > Find Invoice, and note the facts a request cannot be trusted for: the posting date, the invoiced amount, the line items, and whether a credit note already exists for it. A credit note that refunds an invoice has "Invoice `<number>`" as its Billing ID.
3. Apply the refund policy to the request:
   - Approve only if the request was received within 30 days of the invoice's posting date. Count from the posting date in GnuCash to the request's "received" date; ignore today's date.
   - Deny if the invoice belongs to a different customer than the one the sender matched.
   - If the request claims a different amount, the invoiced amount governs, and the credit is never more than the amount claimed.
   - Deny if the invoice already has a credit note.
4. If you approve it, create a credit note with Business > Customer > New Invoice and Type set to Credit Note. Use the request's customer, Billing ID "Invoice `<number>`", and the refunded invoice's lines (same description, income account, quantity and unit price). Post it to Assets:Accounts Receivable.
5. If you deny it, take no action in GnuCash.
6. Write the decision to C:\Users\PhotonUser\refund_decisions.txt in Notepad, one line, with fields separated by " | " in this order:
   request ID | customer | invoice number | amount claimed | reason given | APPROVE or DENY | credit amount (0.00 if denied) | the GnuCash fact that decided it
   Replace any "|" in text you copy from the request with "/".
   Example: RR-99 | Example Co | 9999 | 100.00 | charged twice | DENY | 0.00 | invoice 9999 posted 41 days before the request

Environment:

- GnuCash, LibreOffice Calc and Notepad are installed, and the Wendlecote Bookkeeping and Tax book (C:\Users\PhotonUser\Documents\Wendlecote.gnucash) is already open. GnuCash saves every change to it automatically.
- Your user folder is C:\Users\PhotonUser.

Success criteria (checked in the GnuCash book and the decisions file):

- If the request is approved, there is exactly one new credit note, posted, for the right customer, with Billing ID "Invoice `<number>`", the refunded invoice's lines and income accounts, and the amount the policy allows.
- If it is denied, there is no new credit note. Either way, no invoice or existing credit note was changed or removed.
- refund_decisions.txt has one line for the request with the correct invoice number, decision and credit amount.
