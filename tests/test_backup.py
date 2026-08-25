import csv
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from expense_tracker import (
    CADENCE_MONTHLY,
    CADENCE_YEARLY,
    KIND_BANK,
    add_expense,
    backup_database,
    backup_file_name,
    create_card,
    create_expense,
    create_schema,
    describe_backup,
    export_card_payments_csv,
    export_cards_csv,
    export_subscriptions_csv,
    load_cards,
    load_expenses,
    restore_database,
    save_card,
    set_card_payment,
    set_expense_paid,
    get_paid_expense_ids,
)


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.data_file = self.folder / "expenses.db"
        create_schema(self.data_file)

        self.netflix = create_expense(
            "Netflix", 22.99, "2026-01-03", category="Streaming",
            cadence=CADENCE_MONTHLY, due_day=3,
        )
        add_expense(self.data_file, self.netflix)
        add_expense(self.data_file, create_expense(
            "Domain", 18.0, "2026-01-14", category="Software",
            cadence=CADENCE_YEARLY, due_day=14,
        ))
        self.card = create_card("Chase Freedom", 15)
        save_card(self.data_file, self.card)
        set_card_payment(self.data_file, self.card.id, 2026, 7, 380.10)
        set_expense_paid(self.data_file, self.netflix.id, 2026, 8, True)

    # --- backing up ------------------------------------------------------

    def test_a_backup_holds_everything_the_original_did(self) -> None:
        backup = backup_database(self.data_file, self.folder / "copy.db")

        self.assertEqual(
            sorted(item.description for item in load_expenses(backup)),
            ["Domain", "Netflix"],
        )
        self.assertEqual([card.name for card in load_cards(backup)], ["Chase Freedom"])
        # The part a CSV would lose.
        self.assertIn(self.netflix.id, get_paid_expense_ids(backup, 2026, 8))

    def test_backing_up_into_a_folder_names_the_file(self) -> None:
        destination = self.folder / "somewhere"
        destination.mkdir()
        backup = backup_database(self.data_file, destination)

        self.assertEqual(backup.parent, destination)
        self.assertEqual(backup.name, backup_file_name())
        self.assertIn(date.today().isoformat(), backup.name)

    def test_backing_up_leaves_the_original_alone(self) -> None:
        before = self.data_file.read_bytes()
        backup_database(self.data_file, self.folder / "copy.db")
        self.assertEqual(self.data_file.read_bytes(), before)

    def test_backing_up_nothing_is_refused(self) -> None:
        with self.assertRaises(FileNotFoundError):
            backup_database(self.folder / "absent.db", self.folder / "copy.db")

    # --- describing before trusting --------------------------------------

    def test_a_backup_describes_its_own_contents(self) -> None:
        backup = backup_database(self.data_file, self.folder / "copy.db")
        summary = describe_backup(backup)

        self.assertEqual(summary["subscriptions"], 2)
        self.assertEqual(summary["cards"], 1)
        self.assertEqual(summary["payments"], 2)
        self.assertGreater(summary["size"], 0)

    def test_a_file_that_is_not_a_database_is_refused(self) -> None:
        rubbish = self.folder / "holiday.jpg"
        rubbish.write_bytes(b"\xff\xd8\xff\xe0 this is a photograph")
        with self.assertRaises(ValueError):
            describe_backup(rubbish)

    def test_someone_elses_database_is_refused(self) -> None:
        stranger = self.folder / "notes.db"
        connection = sqlite3.connect(stranger)
        connection.execute("CREATE TABLE notes (id INTEGER, body TEXT)")
        connection.commit()
        connection.close()

        with self.assertRaises(ValueError):
            describe_backup(stranger)

    # --- restoring -------------------------------------------------------

    def test_restoring_brings_everything_back(self) -> None:
        backup = backup_database(self.data_file, self.folder / "copy.db")

        # Lose everything, the way a person would.
        self.data_file.unlink()
        create_schema(self.data_file)
        self.assertEqual(load_expenses(self.data_file), [])

        restore_database(backup, self.data_file)

        self.assertEqual(
            sorted(item.description for item in load_expenses(self.data_file)),
            ["Domain", "Netflix"],
        )
        self.assertIn(self.netflix.id, get_paid_expense_ids(self.data_file, 2026, 8))

    def test_restoring_keeps_what_it_replaced(self) -> None:
        backup = backup_database(self.data_file, self.folder / "copy.db")
        add_expense(self.data_file, create_expense(
            "Added after the backup", 5.0, "2026-08-01", category="Other",
            cadence=CADENCE_MONTHLY, due_day=1,
        ))

        displaced = restore_database(backup, self.data_file)

        self.assertIsNotNone(displaced)
        self.assertTrue(displaced.exists())
        # The restore really did roll back...
        self.assertNotIn(
            "Added after the backup",
            [item.description for item in load_expenses(self.data_file)],
        )
        # ...and the newer data is still recoverable from what was displaced.
        self.assertIn(
            "Added after the backup",
            [item.description for item in load_expenses(displaced)],
        )

    def test_restoring_rubbish_changes_nothing(self) -> None:
        rubbish = self.folder / "holiday.jpg"
        rubbish.write_bytes(b"\xff\xd8\xff\xe0 this is a photograph")
        before = self.data_file.read_bytes()

        with self.assertRaises(ValueError):
            restore_database(rubbish, self.data_file)

        self.assertEqual(self.data_file.read_bytes(), before)


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.data_file = self.folder / "expenses.db"
        create_schema(self.data_file)

        self.card = create_card("Chase Freedom", 15)
        save_card(self.data_file, self.card)
        self.bank = create_card("NIC Asia Savings", kind=KIND_BANK)
        save_card(self.data_file, self.bank)
        set_card_payment(self.data_file, self.card.id, 2026, 7, 380.10)

        netflix = create_expense(
            "Netflix", 22.99, "2026-01-03", category="Streaming",
            cadence=CADENCE_MONTHLY, due_day=3,
        )
        netflix.paid_with = self.card.id
        add_expense(self.data_file, netflix)
        add_expense(self.data_file, create_expense(
            "Domain, renewed", 18.0, "2026-01-14", category="Software",
            cadence=CADENCE_YEARLY, due_day=14,
        ))

    def _read(self, path: Path) -> list:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.reader(handle))

    def test_subscriptions_export_uses_the_headings_people_see(self) -> None:
        path = export_subscriptions_csv(
            load_expenses(self.data_file), load_cards(self.data_file),
            self.folder / "subs.csv", today=date(2026, 8, 24),
        )
        rows = self._read(path)
        self.assertEqual(rows[0][0], "Description")
        self.assertIn("Charged to", rows[0])
        self.assertIn("Per month", rows[0])

    def test_it_names_the_payment_source_not_an_identifier(self) -> None:
        path = export_subscriptions_csv(
            load_expenses(self.data_file), load_cards(self.data_file),
            self.folder / "subs.csv", today=date(2026, 8, 24),
        )
        rows = self._read(path)
        netflix = next(row for row in rows if row[0] == "Netflix")
        self.assertEqual(netflix[-1], "Chase Freedom")
        self.assertNotIn(self.card.id, netflix)

    def test_a_yearly_subscription_reports_a_twelfth_per_month(self) -> None:
        path = export_subscriptions_csv(
            load_expenses(self.data_file), load_cards(self.data_file),
            self.folder / "subs.csv", today=date(2026, 8, 24),
        )
        rows = self._read(path)
        header = rows[0]
        domain = next(row for row in rows if row[0].startswith("Domain"))
        self.assertEqual(domain[header.index("Per month")], "1.50")

    def test_a_comma_in_a_name_does_not_break_the_columns(self) -> None:
        path = export_subscriptions_csv(
            load_expenses(self.data_file), load_cards(self.data_file),
            self.folder / "subs.csv", today=date(2026, 8, 24),
        )
        rows = self._read(path)
        domain = next(row for row in rows if row[0].startswith("Domain"))
        self.assertEqual(domain[0], "Domain, renewed")
        self.assertEqual(len(domain), len(rows[0]))

    def test_cards_export_says_which_are_banks(self) -> None:
        path = export_cards_csv(load_cards(self.data_file), self.folder / "cards.csv")
        rows = self._read(path)
        kinds = {row[0]: row[1] for row in rows[1:]}
        self.assertEqual(kinds["Chase Freedom"], "Card")
        self.assertEqual(kinds["NIC Asia Savings"], "Bank account")

    def test_a_bank_has_no_due_day_in_the_export(self) -> None:
        path = export_cards_csv(load_cards(self.data_file), self.folder / "cards.csv")
        rows = self._read(path)
        bank = next(row for row in rows if row[0] == "NIC Asia Savings")
        self.assertEqual(bank[2], "")

    def test_card_payments_export_names_the_card(self) -> None:
        path = export_card_payments_csv(self.data_file, self.folder / "payments.csv")
        rows = self._read(path)
        self.assertEqual(rows[0], ["Card", "Year", "Month", "Amount", "Recorded on"])
        self.assertEqual(rows[1][0], "Chase Freedom")
        self.assertEqual(rows[1][3], "380.10")

    def test_exporting_with_nothing_recorded_still_writes_a_header(self) -> None:
        empty = self.folder / "empty.db"
        create_schema(empty)
        path = export_card_payments_csv(empty, self.folder / "none.csv")
        self.assertEqual(self._read(path), [list(("Card", "Year", "Month", "Amount", "Recorded on"))])


if __name__ == "__main__":
    unittest.main()
