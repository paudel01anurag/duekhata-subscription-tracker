import tempfile
import unittest
from datetime import date
from pathlib import Path

from expense_tracker import (
    CADENCE_MONTHLY,
    CADENCE_YEARLY,
    add_expense,
    create_card,
    create_expense,
    create_schema,
    due_reminders,
    get_expenses_by_day,
    get_expenses_for_day,
    get_monthly_run_rate,
    get_total_for_month,
    get_upcoming,
    is_still_running,
    load_expenses,
    next_occurrence,
    occurs_on,
    update_expense,
)


def _gym(paused: bool = False):
    expense = create_expense(
        "Gym", 45.0, "2026-01-18", category="Health",
        cadence=CADENCE_MONTHLY, due_day=18,
    )
    expense.paused = paused
    return expense


class PausedTests(unittest.TestCase):
    def test_a_paused_subscription_does_not_bill(self) -> None:
        self.assertTrue(occurs_on(_gym(), date(2026, 9, 18)))
        self.assertFalse(occurs_on(_gym(paused=True), date(2026, 9, 18)))

    def test_it_leaves_the_month_total(self) -> None:
        self.assertEqual(get_total_for_month([_gym()], 2026, 9), 45.0)
        self.assertEqual(get_total_for_month([_gym(paused=True)], 2026, 9), 0.0)

    def test_it_leaves_the_monthly_average(self) -> None:
        """A paused subscription costs nothing to run, so it leaves the run rate.

        This is computed from cadence rather than from occurs_on, so it needs
        its own check: pausing the calendar would not have paused this.
        """
        self.assertEqual(get_monthly_run_rate([_gym()]), 45.0)
        self.assertEqual(get_monthly_run_rate([_gym(paused=True)]), 0.0)

    def test_it_leaves_the_calendar(self) -> None:
        self.assertIn("2026-09-18", get_expenses_by_day([_gym()], 2026, 9))
        self.assertEqual(get_expenses_by_day([_gym(paused=True)], 2026, 9), {})

    def test_it_leaves_the_day_list(self) -> None:
        self.assertEqual(len(get_expenses_for_day([_gym()], date(2026, 9, 18))), 1)
        self.assertEqual(get_expenses_for_day([_gym(paused=True)], date(2026, 9, 18)), [])

    def test_it_leaves_the_upcoming_list(self) -> None:
        self.assertTrue(get_upcoming([_gym()], date(2026, 9, 14), days=14))
        self.assertEqual(get_upcoming([_gym(paused=True)], date(2026, 9, 14), days=14), [])

    def test_it_raises_no_reminder(self) -> None:
        """The whole point of pausing: stop being told about it."""
        active = due_reminders([_gym()], [], date(2026, 9, 15), days_ahead=3)
        self.assertEqual([item.title for item in active], ["Gym"])

        paused = due_reminders([_gym(paused=True)], [], date(2026, 9, 15), days_ahead=3)
        self.assertEqual(paused, [])

    def test_it_has_no_next_due_date(self) -> None:
        self.assertIsNotNone(next_occurrence(_gym(), date(2026, 9, 1)))
        self.assertIsNone(next_occurrence(_gym(paused=True), date(2026, 9, 1)))

    def test_paused_is_not_the_same_as_ended(self) -> None:
        """A pause is reversible and has no end date; the two must not merge."""
        paused = _gym(paused=True)
        self.assertIsNone(paused.ends_on)
        self.assertTrue(is_still_running(paused, date(2026, 9, 1)))

    def test_resuming_puts_it_straight_back(self) -> None:
        expense = _gym(paused=True)
        self.assertEqual(get_total_for_month([expense], 2026, 9), 0.0)

        expense.paused = False
        self.assertEqual(get_total_for_month([expense], 2026, 9), 45.0)


class PausedStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data_file = Path(tempfile.mkdtemp()) / "expenses.db"
        create_schema(self.data_file)

    def test_pausing_survives_a_save_and_load(self) -> None:
        expense = _gym()
        add_expense(self.data_file, expense)
        self.assertFalse(load_expenses(self.data_file)[0].paused)

        expense.paused = True
        update_expense(self.data_file, expense)
        self.assertTrue(load_expenses(self.data_file)[0].paused)

    def test_resuming_survives_too(self) -> None:
        expense = _gym(paused=True)
        add_expense(self.data_file, expense)
        self.assertTrue(load_expenses(self.data_file)[0].paused)

        expense.paused = False
        update_expense(self.data_file, expense)
        self.assertFalse(load_expenses(self.data_file)[0].paused)

    def test_a_database_written_before_pausing_existed_still_opens(self) -> None:
        """The column is added by migration, so old rows default to not paused."""
        import sqlite3

        older = Path(tempfile.mkdtemp()) / "older.db"
        connection = sqlite3.connect(older)
        connection.execute(
            """
            CREATE TABLE expenses (
                id TEXT PRIMARY KEY, description TEXT NOT NULL, amount REAL,
                date TEXT NOT NULL, account TEXT NOT NULL, category TEXT NOT NULL,
                recurring_monthly INTEGER NOT NULL DEFAULT 0, due_day INTEGER,
                expense_type TEXT NOT NULL DEFAULT 'Fixed',
                color TEXT NOT NULL DEFAULT '#f4a261'
            )
            """
        )
        connection.execute(
            "INSERT INTO expenses (id, description, amount, date, account, category,"
            " recurring_monthly, due_day) VALUES ('1', 'Old', 9.0, '2026-01-05', 'Main',"
            " 'Other', 1, 5)"
        )
        connection.commit()
        connection.close()

        create_schema(older)
        recovered = load_expenses(older)
        self.assertEqual(len(recovered), 1)
        self.assertFalse(recovered[0].paused)


if __name__ == "__main__":
    unittest.main()
