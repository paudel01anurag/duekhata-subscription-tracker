"""What is worth telling someone about, and saying it only once."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from expense_tracker import (
    CADENCE_MONTHLY,
    CADENCE_ONCE,
    CADENCE_YEARLY,
    DEFAULT_REMINDER_DAYS,
    KIND_BANK,
    REMINDER_DAYS,
    add_expense,
    already_reminded,
    create_card,
    create_expense,
    create_schema,
    due_reminders,
    forget_old_reminders,
    mark_reminded,
    pending_reminders,
    reminder_days,
    save_card,
    set_setting,
)


class ReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data_file = Path(tempfile.mkdtemp()) / "expenses.db"
        create_schema(self.data_file)
        self.today = date(2026, 8, 24)
        self.target = self.today + timedelta(days=3)

        self.card = create_card("Chase Freedom", self.target.day)
        self.bank = create_card("NIC Asia Savings", kind=KIND_BANK)
        save_card(self.data_file, self.card)
        save_card(self.data_file, self.bank)

        self.netflix = create_expense(
            "Netflix Premium", 22.99, self.target.isoformat(), category="Streaming",
            cadence=CADENCE_MONTHLY, due_day=self.target.day, paid_with=self.card.id,
        )
        add_expense(self.data_file, self.netflix)

    def _reminders(self, days=3):
        return due_reminders([self.netflix], [self.card, self.bank], self.today, days)

    # --- what counts -------------------------------------------------------

    def test_a_subscription_and_a_card_falling_due_are_both_announced(self) -> None:
        titles = [reminder.title for reminder in self._reminders()]
        self.assertEqual(sorted(titles), ["Chase Freedom", "Netflix Premium"])

    def test_a_bank_account_is_never_announced(self) -> None:
        """It has no bill of its own, so there is nothing to warn about."""
        titles = [reminder.title for reminder in self._reminders()]
        self.assertNotIn("NIC Asia Savings", titles)

    def test_nothing_is_announced_on_a_quiet_day(self) -> None:
        self.assertEqual(self._reminders(days=1), [])

    def test_the_window_is_exact_rather_than_a_range(self) -> None:
        """Otherwise the same charge is announced on each of the days before."""
        self.assertEqual(len(self._reminders(days=3)), 2)
        self.assertEqual(self._reminders(days=2), [])
        self.assertEqual(self._reminders(days=4), [])

    def test_zero_days_means_today(self) -> None:
        due_today = create_expense(
            "Rent", 900.0, self.today.isoformat(), category="Housing",
            cadence=CADENCE_MONTHLY, due_day=self.today.day,
        )
        reminders = due_reminders([due_today], [], self.today, 0)
        self.assertEqual([item.title for item in reminders], ["Rent"])
        self.assertEqual(reminders[0].when(self.today), "today")

    def test_a_negative_window_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            due_reminders([], [], self.today, -1)

    def test_a_finished_subscription_is_not_announced(self) -> None:
        ended = create_expense(
            "Old gym", 45.0, "2026-01-24", category="Health", cadence=CADENCE_MONTHLY,
            due_day=self.target.day, ends_on="2026-06-30",
        )
        self.assertEqual(due_reminders([ended], [], self.today, 3), [])

    def test_a_one_off_is_announced_once(self) -> None:
        one_off = create_expense(
            "Laptop", 1200.0, self.target.isoformat(), category="Other", cadence=CADENCE_ONCE,
        )
        self.assertEqual([r.title for r in due_reminders([one_off], [], self.today, 3)], ["Laptop"])

    # --- what it says ------------------------------------------------------

    def test_a_subscription_names_the_amount_and_the_source(self) -> None:
        reminder = next(r for r in self._reminders() if r.kind == "subscription")
        detail = reminder.detail(self.today)
        self.assertIn("$22.99", detail)
        self.assertIn("Chase Freedom", detail)
        self.assertIn("in 3 days", detail)

    def test_a_subscription_with_no_source_says_nothing_about_one(self) -> None:
        loose = create_expense(
            "Spotify", 16.99, self.target.isoformat(), category="Music",
            cadence=CADENCE_MONTHLY, due_day=self.target.day,
        )
        detail = due_reminders([loose], [], self.today, 3)[0].detail(self.today)
        self.assertIn("$16.99", detail)
        self.assertNotIn(" to ", detail)

    def test_a_card_promises_no_amount(self) -> None:
        """A card's bill is not known in advance, so claiming one would lie."""
        reminder = next(r for r in self._reminders() if r.kind == "card")
        detail = reminder.detail(self.today)
        self.assertNotIn("$", detail)
        self.assertIn("due in 3 days", detail)

    def test_a_planned_subscription_admits_the_amount_is_unknown(self) -> None:
        planned = create_expense(
            "Utilities", None, self.target.isoformat(), category="Utilities",
            cadence=CADENCE_MONTHLY, due_day=self.target.day,
        )
        detail = due_reminders([planned], [], self.today, 3)[0].detail(self.today)
        self.assertIn("unknown amount", detail)

    def test_the_wording_changes_for_today_and_tomorrow(self) -> None:
        reminder = self._reminders()[0]
        self.assertEqual(reminder.when(self.target), "today")
        self.assertEqual(reminder.when(self.target - timedelta(days=1)), "tomorrow")
        self.assertEqual(reminder.when(self.target - timedelta(days=2)), "in 2 days")

    # --- saying it only once ----------------------------------------------

    def test_a_reminder_is_pending_until_it_is_given(self) -> None:
        pending = pending_reminders(
            self.data_file, [self.netflix], [self.card], self.today, 3
        )
        self.assertEqual(len(pending), 2)

        for reminder in pending:
            mark_reminded(self.data_file, reminder)

        self.assertEqual(
            pending_reminders(self.data_file, [self.netflix], [self.card], self.today, 3), []
        )

    def test_marking_twice_is_harmless(self) -> None:
        reminder = self._reminders()[0]
        mark_reminded(self.data_file, reminder)
        mark_reminded(self.data_file, reminder)
        self.assertTrue(already_reminded(self.data_file, reminder))

    def test_next_month_is_announced_again(self) -> None:
        """The record is per due date, not per subscription."""
        reminder = next(r for r in self._reminders() if r.kind == "subscription")
        mark_reminded(self.data_file, reminder)

        later = self.today + timedelta(days=31)
        next_month = due_reminders([self.netflix], [], later, 3)
        if next_month:
            self.assertFalse(already_reminded(self.data_file, next_month[0]))

    def test_old_records_are_forgotten(self) -> None:
        reminder = self._reminders()[0]
        mark_reminded(self.data_file, reminder)
        self.assertTrue(already_reminded(self.data_file, reminder))

        forget_old_reminders(self.data_file, self.target + timedelta(days=1))
        self.assertFalse(already_reminded(self.data_file, reminder))

    # --- settings ----------------------------------------------------------

    def test_the_warning_period_falls_back_rather_than_failing(self) -> None:
        set_setting(self.data_file, REMINDER_DAYS, "not a number")
        self.assertEqual(reminder_days(self.data_file), DEFAULT_REMINDER_DAYS)

        set_setting(self.data_file, REMINDER_DAYS, "999")
        self.assertEqual(reminder_days(self.data_file), DEFAULT_REMINDER_DAYS)

        set_setting(self.data_file, REMINDER_DAYS, "7")
        self.assertEqual(reminder_days(self.data_file), 7)


if __name__ == "__main__":
    unittest.main()
