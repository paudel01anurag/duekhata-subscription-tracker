"""Linking a subscription to the card or bank account it is charged to."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from expense_tracker import (
    CADENCE_MONTHLY,
    CADENCE_YEARLY,
    KIND_BANK,
    KIND_CARD,
    add_expense,
    cards_only,
    create_card,
    create_expense,
    create_schema,
    delete_card,
    expenses_charged_to,
    find_card,
    get_total_for_month,
    load_cards,
    load_expenses,
    payment_source_name,
    save_card,
    set_card_payment,
    subscription_run_rate_for_source,
    update_expense,
)


class PaymentSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data_file = Path(tempfile.mkdtemp()) / "expenses.db"
        create_schema(self.data_file)
        self.card = create_card("Chase Freedom", 15)
        self.bank = create_card("NIC Asia Savings", kind=KIND_BANK)
        save_card(self.data_file, self.card)
        save_card(self.data_file, self.bank)

    def _add(self, name, amount, cadence=CADENCE_MONTHLY, paid_with=None, day=3):
        expense = create_expense(
            name, amount, "2026-01-%02d" % day, category="Streaming",
            cadence=cadence, due_day=day, paid_with=paid_with,
        )
        add_expense(self.data_file, expense)
        return expense

    # --- bank accounts are payment sources without a bill ------------------

    def test_a_bank_account_has_no_due_day(self) -> None:
        self.assertIsNone(self.bank.due_day)
        self.assertFalse(self.bank.is_card)
        self.assertTrue(self.card.is_card)

    def test_a_bank_account_may_not_be_given_a_due_day(self) -> None:
        bank = create_card("Everyday", due_day=12, kind=KIND_BANK)
        self.assertIsNone(bank.due_day, "a bank account must not carry a due day")

    def test_a_card_still_requires_one(self) -> None:
        with self.assertRaises(ValueError):
            create_card("No day", kind=KIND_CARD)

    def test_a_payment_source_needs_a_name(self) -> None:
        with self.assertRaises(ValueError):
            create_card("   ", kind=KIND_BANK)

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            create_card("Odd", 4, kind="wallet")

    def test_both_kinds_survive_a_round_trip(self) -> None:
        stored = {card.name: card for card in load_cards(self.data_file)}
        self.assertEqual(stored["Chase Freedom"].kind, KIND_CARD)
        self.assertEqual(stored["NIC Asia Savings"].kind, KIND_BANK)
        self.assertIsNone(stored["NIC Asia Savings"].due_day)

    def test_only_cards_have_bills_to_pay(self) -> None:
        names = [card.name for card in cards_only(load_cards(self.data_file))]
        self.assertEqual(names, ["Chase Freedom"])

    # --- the link ----------------------------------------------------------

    def test_a_subscription_remembers_where_it_is_charged(self) -> None:
        self._add("Netflix", 22.99, paid_with=self.card.id)
        stored = load_expenses(self.data_file)[0]
        self.assertEqual(stored.paid_with, self.card.id)
        self.assertEqual(
            payment_source_name(load_cards(self.data_file), stored.paid_with), "Chase Freedom"
        )

    def test_an_unlinked_subscription_says_nothing(self) -> None:
        self._add("Spotify", 16.99)
        stored = load_expenses(self.data_file)[0]
        self.assertIsNone(stored.paid_with)
        self.assertEqual(payment_source_name(load_cards(self.data_file), None), "")

    def test_a_subscription_can_be_charged_to_a_bank_account(self) -> None:
        self._add("Rent", 900.0, paid_with=self.bank.id)
        stored = load_expenses(self.data_file)[0]
        self.assertEqual(
            payment_source_name(load_cards(self.data_file), stored.paid_with), "NIC Asia Savings"
        )

    def test_what_is_charged_to_a_source(self) -> None:
        self._add("Netflix", 22.99, paid_with=self.card.id, day=3)
        self._add("Spotify", 16.99, paid_with=self.card.id, day=5)
        self._add("Rent", 900.0, paid_with=self.bank.id, day=1)
        self._add("Unlinked", 5.0, day=7)

        on_card = [
            item.description
            for item in expenses_charged_to(load_expenses(self.data_file), self.card.id)
        ]
        self.assertEqual(on_card, ["Netflix", "Spotify"])

    def test_the_link_survives_an_edit(self) -> None:
        expense = self._add("Netflix", 22.99, paid_with=self.card.id)
        set_card_payment(self.data_file, self.card.id, 2026, 8, 400.0)

        expense.amount = 24.99
        update_expense(self.data_file, expense)

        stored = load_expenses(self.data_file)[0]
        self.assertEqual(stored.amount, 24.99)
        self.assertEqual(stored.paid_with, self.card.id)

    # --- what a source costs per month ------------------------------------

    def test_a_sources_run_rate_normalises_by_cadence(self) -> None:
        self._add("Netflix", 22.99, paid_with=self.card.id)
        self._add("Domain", 120.0, cadence=CADENCE_YEARLY, paid_with=self.card.id, day=9)

        # 22.99 monthly + 120/12 yearly = 32.99
        self.assertAlmostEqual(
            subscription_run_rate_for_source(load_expenses(self.data_file), self.card.id),
            32.99,
            places=2,
        )

    def test_a_source_with_nothing_on_it_costs_nothing(self) -> None:
        self.assertEqual(
            subscription_run_rate_for_source(load_expenses(self.data_file), self.bank.id), 0.0
        )

    # --- deleting a source must not orphan a subscription -----------------

    def test_deleting_a_source_unlinks_rather_than_deletes(self) -> None:
        self._add("Netflix", 22.99, paid_with=self.card.id)
        delete_card(self.data_file, self.card.id)

        remaining = load_expenses(self.data_file)
        self.assertEqual(
            [item.description for item in remaining], ["Netflix"],
            "the subscription itself must survive",
        )
        self.assertIsNone(
            remaining[0].paid_with, "it must no longer point at a deleted source"
        )
        self.assertIsNone(find_card(load_cards(self.data_file), self.card.id))

    def test_deleting_a_source_leaves_other_links_alone(self) -> None:
        self._add("Netflix", 22.99, paid_with=self.card.id)
        self._add("Rent", 900.0, paid_with=self.bank.id, day=1)
        delete_card(self.data_file, self.card.id)

        by_name = {item.description: item for item in load_expenses(self.data_file)}
        self.assertIsNone(by_name["Netflix"].paid_with)
        self.assertEqual(by_name["Rent"].paid_with, self.bank.id)

    # --- a bank account has no due date anywhere --------------------------

    def test_a_bank_account_never_lands_on_the_calendar(self) -> None:
        from expense_tracker import (
            card_due_date, get_cards_due_between, get_cards_due_in_month,
        )
        from datetime import date as _date

        cards = load_cards(self.data_file)
        self.assertIsNone(card_due_date(self.bank, 2026, 8))

        by_day = get_cards_due_in_month(cards, 2026, 8)
        placed = [card.name for day_cards in by_day.values() for card in day_cards]
        self.assertEqual(placed, ["Chase Freedom"])

        upcoming = get_cards_due_between(cards, _date(2026, 8, 1), days=31)
        self.assertEqual([card.name for _day, card in upcoming], ["Chase Freedom"])

    # --- the rule that must not break -------------------------------------

    def test_linking_does_not_move_money_between_the_two_halves(self) -> None:
        """A card payment must still never count as spending."""
        self._add("Netflix", 22.99, paid_with=self.card.id)
        set_card_payment(self.data_file, self.card.id, 2026, 8, 412.60)

        self.assertEqual(get_total_for_month(load_expenses(self.data_file), 2026, 8), 22.99)

    # --- older databases ---------------------------------------------------

    def test_a_database_written_before_the_link_is_migrated(self) -> None:
        legacy = self.data_file.parent / "legacy.db"
        connection = sqlite3.connect(legacy)
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
            """
            CREATE TABLE cards (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, due_day INTEGER NOT NULL,
                color TEXT NOT NULL DEFAULT '#5b8ac7', notes TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            "INSERT INTO expenses (id, description, amount, date, account, category,"
            " recurring_monthly, due_day)"
            " VALUES ('a', 'Netflix', 15.0, '2026-08-10', 'Main', 'Subscription', 1, 10)"
        )
        connection.execute("INSERT INTO cards (id, name, due_day) VALUES ('c1', 'Old Card', 9)")
        connection.commit()
        connection.close()

        create_schema(legacy)

        expense = load_expenses(legacy)[0]
        self.assertIsNone(expense.paid_with, "an old row has no source, and that is not an error")

        card = load_cards(legacy)[0]
        self.assertEqual(card.kind, KIND_CARD, "everything stored before was a credit card")
        self.assertEqual(card.due_day, 9)


if __name__ == "__main__":
    unittest.main()
