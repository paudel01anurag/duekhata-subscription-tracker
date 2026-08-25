import tempfile
import unittest
from datetime import date
from pathlib import Path

from expense_tracker import (
    CADENCE_MONTHLY,
    CURRENCIES,
    DEFAULT_CURRENCY,
    add_expense,
    create_card,
    create_expense,
    create_schema,
    current_currency,
    due_reminders,
    export_subscriptions_csv,
    load_currency,
    money,
    reset_currency,
    save_currency,
    set_currency,
)


class MoneyTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_currency()

    def tearDown(self) -> None:
        reset_currency()

    def test_the_default_is_a_dollar(self) -> None:
        self.assertEqual(current_currency(), "$")
        self.assertEqual(money(1234.5), "$1,234.50")

    def test_a_glyph_sits_against_the_digits(self) -> None:
        set_currency("£")
        self.assertEqual(money(1234.5), "£1,234.50")

    def test_letters_are_given_a_space(self) -> None:
        """"Rs.1,200" is hard to read; "Rs. 1,200" is not."""
        set_currency("Rs.")
        self.assertEqual(money(1200), "Rs. 1,200.00")

    def test_a_typed_symbol_of_letters_infers_the_space(self) -> None:
        set_currency("kr")
        self.assertEqual(money(50), "kr 50.00")

    def test_a_typed_glyph_infers_no_space(self) -> None:
        set_currency("₺")
        self.assertEqual(money(50), "₺50.00")

    def test_thousands_are_grouped_and_cents_kept(self) -> None:
        set_currency("$")
        self.assertEqual(money(1234567.891), "$1,234,567.89")

    def test_whole_numbers_can_be_asked_for(self) -> None:
        """The charts label their slices without cents."""
        self.assertEqual(money(1234.6, 0), "$1,235")
        self.assertEqual(money(1234.2, 0), "$1,234")

    def test_an_exact_half_rounds_the_way_python_does(self) -> None:
        """Recorded rather than corrected.

        Python rounds a tie to the even number, so 1234.5 becomes 1,234 and
        1235.5 becomes 1,236. That is what the application did before amounts
        were funnelled through money(), and it only ever affects a chart label
        by one unit, so it is left alone rather than quietly changed.
        """
        self.assertEqual(money(1234.5, 0), "$1,234")
        self.assertEqual(money(1235.5, 0), "$1,236")

    def test_nothing_formats_as_nothing(self) -> None:
        self.assertEqual(money(None), "")

    def test_zero_is_still_shown(self) -> None:
        self.assertEqual(money(0), "$0.00")

    def test_a_negative_keeps_its_sign_readable(self) -> None:
        set_currency("$")
        self.assertEqual(money(-51.75), "$-51.75")

    def test_an_empty_choice_falls_back_rather_than_vanishing(self) -> None:
        set_currency("   ")
        self.assertEqual(current_currency(), DEFAULT_CURRENCY)

    def test_every_offered_currency_formats(self) -> None:
        for code, symbol, _space, name in CURRENCIES:
            set_currency(symbol)
            rendered = money(9.5)
            self.assertIn(symbol, rendered, code)
            self.assertTrue(rendered.endswith("9.50"), code + " -> " + rendered)


class CurrencyStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_currency()
        self.data_file = Path(tempfile.mkdtemp()) / "expenses.db"
        create_schema(self.data_file)

    def tearDown(self) -> None:
        reset_currency()

    def test_a_new_database_is_dollars(self) -> None:
        self.assertEqual(load_currency(self.data_file), "$")

    def test_a_choice_survives_a_restart(self) -> None:
        save_currency(self.data_file, "Rs.")
        reset_currency()
        self.assertEqual(current_currency(), "$")

        load_currency(self.data_file)
        self.assertEqual(current_currency(), "Rs.")
        self.assertEqual(money(1200), "Rs. 1,200.00")

    def test_changing_it_takes_effect_at_once(self) -> None:
        save_currency(self.data_file, "₹")
        self.assertEqual(money(75), "₹75.00")

    def test_amounts_themselves_are_untouched(self) -> None:
        """Only the symbol changes. Nothing is converted, so no figure moves."""
        add_expense(self.data_file, create_expense(
            "Netflix", 22.99, "2026-01-03", category="Streaming",
            cadence=CADENCE_MONTHLY, due_day=3,
        ))
        save_currency(self.data_file, "£")

        from expense_tracker import load_expenses, get_total_for_month
        self.assertEqual(load_expenses(self.data_file)[0].amount, 22.99)
        self.assertEqual(get_total_for_month(load_expenses(self.data_file), 2026, 9), 22.99)


class CurrencyReachesEverythingTests(unittest.TestCase):
    """The symbol has to reach the places that are easy to forget."""

    def setUp(self) -> None:
        reset_currency()
        self.folder = Path(tempfile.mkdtemp())
        self.data_file = self.folder / "expenses.db"
        create_schema(self.data_file)
        self.expense = create_expense(
            "Netflix", 22.99, "2026-01-26", category="Streaming",
            cadence=CADENCE_MONTHLY, due_day=26,
        )
        add_expense(self.data_file, self.expense)

    def tearDown(self) -> None:
        reset_currency()

    def test_a_reminder_names_the_chosen_currency(self) -> None:
        set_currency("Rs.")
        reminders = due_reminders([self.expense], [], date(2026, 8, 23), days_ahead=3)
        detail = reminders[0].detail(date(2026, 8, 23))
        self.assertIn("Rs. 22.99", detail)
        self.assertNotIn("$", detail)

    def test_the_csv_export_carries_plain_numbers(self) -> None:
        """A spreadsheet wants a number it can add up, not a decorated string."""
        set_currency("£")
        path = export_subscriptions_csv(
            [self.expense], [], self.folder / "subs.csv", today=date(2026, 8, 23)
        )
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("22.99", text)
        self.assertNotIn("£22.99", text)


if __name__ == "__main__":
    unittest.main()
