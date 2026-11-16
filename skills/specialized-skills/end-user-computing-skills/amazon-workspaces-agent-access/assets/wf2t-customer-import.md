Task:
Register the firm's new client as a GnuCash customer. It is listed in the CRM export C:\Users\PhotonUser\sample-customer-export.csv, and the CRM team has already converted that export to GnuCash's customer import layout in C:\Users\PhotonUser\customers-import.csv (19 fields, no header row).

1. Open the export and read the client's Payment Terms and Discount %. Then compare the import file with it: the import file must hold exactly one row, for that client, with the same ID, name, contact, address, phone and email, and its ID must not belong to an existing customer. If it holds any other row or would change an existing customer, stop and report it instead of importing.
2. Import customers-import.csv with File > Import > Import Customers and Vendors..., choosing Customer as the import type and a comma-separated option. Confirm in the Preview pane that the columns line up with the expected fields, then import. The statistics should report 1 customer imported and none ignored. Do not edit either file.
3. Billing terms and discounts cannot be imported. No billing terms exist yet, so first create the client's term in Business > Billing Terms Editor as a "Days" term (Net N is due in N days; Due on receipt is due in 0 days). Then open the new customer and set its Terms and Discount from the export. Discount % is a percentage: 2.5 means 2.5%.

Environment:

- GnuCash and LibreOffice Calc are installed, and the Wendlecote Bookkeeping and Tax book (C:\Users\PhotonUser\Documents\Wendlecote.gnucash) is already open. GnuCash saves every change to it automatically.
- Your user folder is C:\Users\PhotonUser.

Success criteria (checked in the GnuCash book):

- The book holds its 7 existing customers, unchanged, plus exactly 1 new one.
- The new customer's ID, company, billing name, address lines 1 to 4, phone and email are as in the import file.
- The billing term exists exactly once, with the right number of days.
- The new customer has the billing term and discount from its export row.
