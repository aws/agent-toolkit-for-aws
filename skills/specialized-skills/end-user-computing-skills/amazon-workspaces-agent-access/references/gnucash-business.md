# GnuCash business workflows on the desktop

GnuCash business workflows (customers, invoices, credit notes) on the remote Windows desktop. Covers opening menu items with the keyboard, setting invoice/credit-note header fields such as Billing ID without getting stuck, entering lines, and posting them.

## Opening GnuCash menu items: keys open the menu, a click picks the item

Never click a GnuCash menu title (File, Business, …). When the display lags, the click toggles the menu shut or lands on the toolbar below it, which opens stray Edit Account / New Account dialogs.

Never pick the final item by counting arrow keys either. The highlight in a newly opened menu is unpredictable, so a counted down/enter opens the wrong thing: Save As, New File, Business Linked Documents or another menu.

1. GnuCash is already running with the book open. Never launch_application gnucash.
   - A second copy stops at a "could not obtain the lock" prompt. If you see it, click **Quit**, never Open Anyway.
   - To bring the running window forward, click its taskbar button ONCE, then wait for a screenshot that shows it. If you click the taskbar button of the window that is already in front, Windows minimizes it.
2. Bring the GnuCash main window to the front and make sure no dialog you still need is open. Then send ONE response that holds all of these tool calls:
   - move_pointer to x=900, y=500, which keeps the pointer off the menus;
   - the keys for your item, one key action per key (list below);
   - a screenshot.

   Keys for each item:
   - Business > Customer > any item: escape, escape, alt+b, right
   - Business > Billing Terms Editor or Sales Tax Table: escape, escape, alt+b
   - File > Import > any item: escape, escape, alt+f
3. A menu opened with keys stays open until you click or press escape. Find your item by its label in the screenshot and left_click it once.
   - **Customer submenu** (opens to the right of the Business menu): Customers Overview, New Customer…, Find Customer…, New Invoice…, Find Invoice…, New Job…, Find Job…, Process Payment…
   - **Business menu**: Customer ▸, Vendor ▸, Employee ▸, Business Linked Documents, Sales Tax Table, Billing Terms Editor
   - **File menu**: click **Import** and take a screenshot. Then click **Import Customers & Vendors…** in the submenu that opens to its right.
   - Never click New File, and never press ctrl+n while GnuCash is in front. Either one replaces the open book.
   - If the screenshot shows no menu yet, take another screenshot. If there is still none after two, send the step-2 batch again; its escapes make it safe to repeat.
   - If Business is open but its Customer submenu isn't, click **Customer**, then take a screenshot.
4. After the click, take screenshots until the dialog or tab appears; it can take 30 s. Send nothing else in the meantime. If the wrong item opened, Cancel or close it and go back to step 2.

## GnuCash invoices and credit notes: header fields (Billing ID, Customer, Terms)

**Trap:** in an open *Edit Invoice* / *Edit Credit Note* tab, the entries register keeps the keyboard. Clicking Billing ID in the tab header shows a caret there, but what you type lands in the register's blank line (Date or Description cell). Escape, Tab/Shift+Tab, triple-click, select-all, Backspace and waiting do not fix it. Never type into the header area of an invoice tab. Set header fields only in a dialog:

1. **New Invoice dialog** (Business > Customer > New Invoice): fill it in completely before OK.
   - Credit note: click the Credit Note radio first. It shifts the layout, so take a screenshot before the next click.
   - Customer: if it is not already filled, type the exact GnuCash name and press Tab, or use **Select…** to pick the existing customer. Take a screenshot before clicking Billing ID, because a name-completion popup can swallow the next click.
   - Billing ID: click it and type the value once.
   - The display lags several seconds behind input. If a field you just typed into looks empty or unchanged, take another screenshot instead of typing again. Retype only after triple-clicking the field, so the new text replaces everything in it.
   - Click OK only when a fresh screenshot shows Customer and Billing ID exactly right.
2. **Header wrong once the tab is open**: click the toolbar button **Edit Invoice** (**Edit Credit Note** on a credit note; just right of New Invoice / New Credit Note). It opens the same fields in a separate dialog where typing works. Triple-click Billing ID, type the value, check a screenshot, then click OK. Do this before you post, because a posted document cannot be edited.
3. If stray keys went into the register's blank line, click the toolbar **Cancel** to throw that unsaved line away before entering real lines.
4. Never create a second invoice or credit note to get a clean header. The book must end with exactly one new one.

## Entering lines in the entries register

When GnuCash lags, keys and clicks sent as separate actions go astray:

- A Tab or click that doesn't take effect makes the next value join the previous cell. An account with a number stuck on the end brings up a create-account prompt.
- Tabbing out of Description copies an older entry with the same description into the row and moves the cursor.

Enter every line this way:

1. Click the **Income Account** cell of the empty last row and take a screenshot. Go on only when the status bar at the bottom reads "Enter the income/expense account for the Entry…".
2. Send ONE type_text with the full account path exactly as the task or source document gives it, the quantity and the unit price (plain numbers), separated by real tab characters: `<account>\t<quantity>\t<unit price>`. Write each `\t` with one backslash in the JSON string. Leave Action, discount and tax cells empty. In the same batch, click that row's **Description** cell and take a screenshot.
3. When the screenshot shows each value in its own cell and the cursor in Description, type_text the description by itself (no Tab), then take a screenshot.
4. If GnuCash appended highlighted text to the description, press Delete. Then press Enter once.
5. The line is recorded when **Total:** at the bottom left includes it and a new empty row appears below it. This can take up to a minute.
   - Until then, send nothing but waits and screenshots. Anything else you type or click in the meantime lands in the next row once GnuCash catches up.
   - If nothing has changed after about a minute, press Enter once more (harmless on a recorded line) and go back to waiting.
6. Fixing mistakes:
   - An unrecorded line is wrong, or GnuCash offers to create an account (answer **No**): click toolbar **Cancel** and redo the line from step 1.
   - A recorded line is wrong: select it, click toolbar **Delete**, confirm, and enter it again.
   - Never repair a cell with runs of Backspace/Home/Shift.
   - A literal `\t` in a cell means the tab was double-escaped.

## Posting: nothing is posted until you OK a Post dialog

- Entering lines only saves a draft, and closing the tab does not post it. "UNPAID", a greyed Date Opened and an "Edit …" tab title all appear on drafts too. They do NOT mean posted.
- **Invoice tab:** **Post** is the right-most toolbar button.
- **Credit-note tab:** the longer "…Credit Note" labels push Post off the toolbar. Click the **⌄ chevron at the far right end of the toolbar** (right of Blank) and choose **Post** from its dropdown.
- **Fallback if the chevron fails:** Business > Customer > Find Invoice. Search by the new document's ID from its tab title, select its row in the results, then click the dialog's **Post** button.
- In the Post dialog, check that the post-to account is the receivable account the task names, keep the dates, and click OK.
- **Posted check:** posted means a fresh screenshot of the document shows **Date Posted** and **Posted Account** fields in its header (and the toolbar offers Unpost). Do this once, right after OK, before writing any output file or finishing. If those fields are absent, the document is not posted yet, so post it.
