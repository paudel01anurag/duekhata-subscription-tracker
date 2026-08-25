# Changelog

What changed in each version. Newest first. Every version can be downloaded from the
[releases page](https://github.com/paudel01anurag/duekhata-subscription-tracker/releases).

## v3.6.0 — 25 August 2026

Amounts no longer have to be dollars.

**Added**

- **A currency setting.** Ten are offered — US dollar, Nepalese rupee, Indian rupee, pound sterling,
  euro, Australian and Canadian dollar, yen, dirham and Singapore dollar — and the box can be typed
  into, so a symbol that is not listed can simply be entered. The dollar remains the default, and a
  preview shows a real amount before anything is saved.

  **Nothing is converted.** This changes the symbol amounts are drawn with and nothing else: no rate
  is looked up, no stored figure moves, and one installation is one currency.

- The entry form's amount field now names the currency it is asking for, so it reads
  **Amount (Rs.)** rather than just Amount.

**Changed**

- Reminders moved into a **Settings** dialog alongside the currency, reached by the gear in the
  sidebar where the bell used to be. Two settings did not justify two icons.
- Amount boxes accept the symbol back, so "Rs. 1,200" is understood as readily as "1200". Previously
  only a dollar sign was stripped.

## v3.5.0 — 25 August 2026

Your data can leave the machine it lives on, a subscription can be paused rather than deleted, and
the cards you have entered are finally visible as a picture.

**Added**

- **Backup, restore and export**, behind the save icon in the sidebar. A backup is the whole
  database and puts everything back, including which months you marked paid. Restoring keeps what it
  replaced, so restoring the wrong file can be undone, and a file that is not a DueKhata database is
  refused before anything is overwritten. The CSV export beside it is for reading in a spreadsheet
  and deliberately does not come back in.
- **Pausing.** A frozen gym membership can be stopped without ending or deleting it: nothing bills,
  nothing appears on the calendar, no reminder is raised, and the monthly average drops. Its history
  is kept and one tick brings it back.
- **Sorting by clicking a column heading**, in the subscriptions list and in Cards & banks. Click to
  sort, click again to reverse. No new controls were added; the headings that were already there
  became the way to sort.
- **Spending charted by card.** Statistics can group the year by which card or bank account it is
  charged to, as well as by category, and either can be narrowed to a single month.

**Changed**

- The Cards view is now **Cards & banks**, and its button **Add card or bank**. Bank accounts have
  been supported since v3.4.0, but every label around the control that creates them said "card", so
  nobody could tell they belonged there.

**Fixed**

- The share chart drew nothing when a single slice was the whole total — which is the state before
  any subscription has been given a payment source. Tk treats an arc of a full circle as an arc of
  nothing.

## v3.4.0 — 24 August 2026

Subscriptions can say where they are charged, and DueKhata can tell you before a payment lands.

**Added**

- **Payment sources.** A subscription can now record which card or bank account it is charged to.
  Bank accounts live alongside cards, and each payment source shows how many subscriptions it carries
  and what they cost per month — so when a card is replaced, the list of what to update is on screen.
- **Reminders.** DueKhata can raise a Windows notification a few days before a payment is due, naming
  the amount and the card it will be charged to. Off by default; the bell in the sidebar switches it
  on and chooses how much warning and at what time.

  It works without the application running: Windows Task Scheduler starts a check once a day, which
  raises anything due and exits. Nothing runs in the background, and nothing reaches the network.

**Fixed**

- The "Charged to" dropdown was invisible, because it shared a grid cell with the "Mark as paid this
  month" checkbox and was drawn underneath it.
- Record identifiers were built from the clock alone, so two records created in the same instant
  could share one. Since payments are matched to their subscription by identifier, that meant marking
  one paid could mark another, and deleting one could delete another. Found by continuous integration
  on its first run, having never once reproduced locally.
- Reminders lost the dollar amount, announcing "Charging .99" instead of "Charging $22.99", because
  PowerShell expanded `$22` as a variable on the way to the notification.

## v3.3.0 — 21 August 2026

Credit cards get their own place, the dashboard stops making a yearly renewal look like a mistake,
and accounts are gone.

**Added**

- **Cards.** Credit cards are tracked for their due date and for what was actually paid each month,
  shown against the month before so you can see whether what you are paying down is going up or
  coming down. Payments are entered a year at a time, so filling in what you have already paid this
  year is one dialog rather than twelve prompts. A tile carries the total paid on cards this year.
- **Average per month.** Beside what bills this month, the dashboard now shows what your
  subscriptions cost per month on average — a yearly membership counts as a twelfth. A month made
  high by yearly or one-off billing says so, so the figure no longer looks wrong.
- Search and filter in the subscription list, by name, category or billing rhythm, with a count of
  what is showing.
- A wordmark in the sidebar.

**Changed**

- **Accounts have been removed.** The Main / Spouse / Shared filter went unused in practice: this
  tracks one household's shared money, and splitting it by which account it came from invented a
  distinction nobody felt. Nothing stored was deleted, and no existing entry needs changing.
- **"Ends on" is a date picker** rather than a plain box that never said what format it wanted. It
  stays blank until you tick *Ends on a date*.
- Statistics can be drawn as a donut or as ranked bars.
- Card payments are **never** counted as spending. Paying a card settles purchases that are already
  recorded as subscriptions, so counting the payment would count the same money twice.

**Fixed**

- **Editing a subscription from the Subscriptions list crashed.** It has been broken since v3.0.0;
  editing from the calendar worked, which is why it went unnoticed.
- The calendar was squeezed. The day list beside it took width it had no use for while the calendar
  starved. At 1680px a day cell went from 111px to 141px.
- The STATUS column in the day list was clipped off the edge of the panel.
- The Cards description kept a light background in dark mode.

**Download**

- The release now carries the executable on its own as well as the ZIP, so it can be run without
  extracting anything first.

## v3.2.0 — 19 August 2026

**Added**

- A wordmark in the sidebar, so the application says its own name.
- Filters in the Subscriptions view: a search box that matches both the name and the category, a
  category list and a repeats list. A count above the table says how many of the total are showing.
- Statistics can now be grouped by category or by account, and drawn as a donut or as ranked bars.
  The donut carries the year's total in its centre.

**Fixed**

- The calendar was squeezed. The day list beside it grew as the window grew, taking width it had no
  use for, while the calendar starved; it is now a fixed width and every spare pixel goes to the
  calendar. At 1680px a cell went from 111px to 141px. The default window also grew to 1360x880,
  which the sidebar had made necessary and nobody had accounted for.
- The STATUS column in the day list was clipped off the edge of the panel.

## v3.1.0 — 19 August 2026

**Renamed to DueKhata.** *Due* for what is owed, *khata* (खाता) for the ledger it is written in.

**Changed**

- The application, the executable and the data folder are now named DueKhata.

**Migration**

- Upgrading from Subscription Tracker keeps everything. On first run the old
  `%LOCALAPPDATA%\SubscriptionTracker` folder is copied to `%LOCALAPPDATA%\DueKhata`, subscriptions
  and login included. The old folder is left in place as a fallback and can be deleted once you are
  satisfied nothing is missing.

## v3.0.0 — 18 August 2026

A new layout. The calendar is still here, but it is now one view among four rather than the whole
application.

**Added**

- A dashboard: monthly totals, spending by category, what is due in the next fortnight, and the
  year's spending month by month.
- A Subscriptions view listing everything tracked, with how often each repeats and when it is next
  due, soonest first. Finished subscriptions sort to the bottom.
- A Statistics view: monthly spending across the year, and each category's share of it.
- A sidebar for moving between the four views. The account filter and the Add button stay in place
  while switching.

**Changed**

- Column headings sit over their data rather than floating mid-column.
- Font selection falls back through the macOS and Linux system faces instead of assuming Segoe is
  installed.
- Build ZIPs are written to `dist\archive`, leaving `dist` holding only the current executable.

**Unchanged**

- How repeat dates are worked out. Entries from v2 behave exactly as before, and no migration is
  needed.

## v2.0.0 — 14 August 2026

Recurrence became a real model rather than a single flag, and subscriptions became editable.

**Added**

- Five billing rhythms: one-off, weekly, monthly, quarterly and yearly. An annual renewal now
  appears once a year instead of every month or never.
- A start date and an optional end date, so a cancelled subscription stops filling the calendar.
- Editing an existing subscription, without losing any month already marked as paid.
- A local username and password gate.
- A redesigned interface: warm light and dark themes, rounded surfaces, coloured payment chips on
  each billing day.

**Changed**

- A subscription no longer appears in months before its start date. This is the behaviour change
  most likely to be noticed: months earlier than a subscription's start now look emptier, correctly.
- Old databases migrate automatically. Entries that were marked recurring become monthly; the rest
  become one-off and may need their cadence setting by hand.

**Fixed**

- Running `python main.py` hung with no error. The login dialog was created while the main window
  was hidden, which left it invisible and the program waiting on a window nobody could see.
- Editing a subscription destroyed its payment history, because the underlying write deleted and
  reinserted the row.
- The calendar shrank whenever a dialog opened, and never recovered.
- Packaged builds could copy a database sitting next to the source into the new user's profile.

## v1 — 7 to 9 August 2026

The first working version, shared as a build rather than a tagged release.

- A month calendar with subscriptions shown on their due day.
- Fixed and variable monthly payments, with description, amount, date, account, category and colour.
- Projected and remaining totals for the month, and filtering by account.
- Marking subscriptions paid or pending.
- Warm light and dark themes.
- Local SQLite storage under `%LOCALAPPDATA%`.
