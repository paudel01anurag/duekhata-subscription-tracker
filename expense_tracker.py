from __future__ import annotations

import calendar
import csv
import json
import secrets
import sqlite3
import textwrap
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, List, Optional, Set


KIND_CARD = "card"
KIND_BANK = "bank"
PAYMENT_KINDS = (KIND_CARD, KIND_BANK)

KIND_LABELS = {KIND_CARD: "Card", KIND_BANK: "Bank account"}

CADENCE_ONCE = "once"
CADENCE_WEEKLY = "weekly"
CADENCE_MONTHLY = "monthly"
CADENCE_QUARTERLY = "quarterly"
CADENCE_YEARLY = "yearly"

# Ordered for presentation in the user interface.
CADENCES = (
    CADENCE_ONCE,
    CADENCE_WEEKLY,
    CADENCE_MONTHLY,
    CADENCE_QUARTERLY,
    CADENCE_YEARLY,
)

CADENCE_LABELS = {
    CADENCE_ONCE: "One-off",
    CADENCE_WEEKLY: "Every week",
    CADENCE_MONTHLY: "Every month",
    CADENCE_QUARTERLY: "Every 3 months",
    CADENCE_YEARLY: "Every year",
}

LABELS_TO_CADENCE = {label: cadence for cadence, label in CADENCE_LABELS.items()}


@dataclass
class Card:
    """A payment source: a credit card, or a bank account.

    A card payment is a settlement, not a purchase: the spending happened when
    the card was used, and those items are recorded separately. So a card
    carries no amount of its own — only what was actually paid each month,
    which is a different number every time.

    A bank account is the same idea with less to it. Money leaves it when a
    subscription bills, so there is no separate bill to pay and no due day of
    its own; `due_day` is None and nothing is ever recorded against it. It
    exists so a subscription can say where it is charged.
    """

    id: str
    name: str
    due_day: Optional[int] = None
    color: str = "#5b8ac7"
    notes: str = ""
    kind: str = KIND_CARD

    @property
    def is_card(self) -> bool:
        return self.kind == KIND_CARD


@dataclass
class Expense:
    id: str
    description: str
    amount: Optional[float]
    date: str
    # The application used to filter by account (Main / Spouse / Shared). Real
    # use showed nobody ever switched it, so the filter is gone. The field is
    # kept and defaulted so no stored data is destroyed and the idea could come
    # back without a migration.
    account: str
    category: str
    recurring_monthly: bool = False
    due_day: Optional[int] = None
    expense_type: str = "Fixed"
    color: str = "#f4a261"
    # How often the subscription bills. `date` is the first billing date and
    # `ends_on` the last one, inclusive; None means it has not been cancelled.
    cadence: str = ""
    ends_on: Optional[str] = None
    # Which card or bank account this is charged to, as a Card id. None means
    # it has not been said. Purely a label: linking a subscription to a card
    # never moves money between the two halves of the application.
    paid_with: Optional[str] = None
    # Temporarily not billing — a frozen gym membership, a service stopped for
    # the winter. Distinct from an end date, which says it is over for good, and
    # from deleting it, which throws the history away.
    paused: bool = False

    def __post_init__(self) -> None:
        # `cadence` supersedes the older `recurring_monthly` flag. Normalising
        # here keeps the two consistent no matter how the record was built:
        # from the database, from legacy JSON, or directly in a test.
        cadence = (self.cadence or "").strip().lower()
        if cadence not in CADENCES:
            cadence = CADENCE_MONTHLY if self.recurring_monthly else CADENCE_ONCE
        self.cadence = cadence
        self.recurring_monthly = cadence != CADENCE_ONCE
        self.ends_on = (self.ends_on or "").strip() or None


def _json_fallback_path(data_file: Path) -> Path:
    return data_file.with_suffix(".json")


@contextmanager
def _connect(data_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(data_file)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _migrate_expense_columns(connection: sqlite3.Connection) -> None:
    """Add the cadence and end-date columns to databases created before them.

    Existing rows only carried the boolean `recurring_monthly`, so their cadence
    is back-filled from it rather than taking the column default. Anything that
    was recurring becomes monthly; everything else becomes a one-off.
    """
    existing = {row[1] for row in connection.execute("PRAGMA table_info(expenses)").fetchall()}

    if "cadence" not in existing:
        connection.execute("ALTER TABLE expenses ADD COLUMN cadence TEXT")
    if "ends_on" not in existing:
        connection.execute("ALTER TABLE expenses ADD COLUMN ends_on TEXT")
    if "paid_with" not in existing:
        connection.execute("ALTER TABLE expenses ADD COLUMN paid_with TEXT")
    if "paused" not in existing:
        connection.execute("ALTER TABLE expenses ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")

    connection.execute(
        """
        UPDATE expenses
        SET cadence = CASE WHEN recurring_monthly = 1 THEN ? ELSE ? END
        WHERE cadence IS NULL OR TRIM(cadence) = ''
        """,
        (CADENCE_MONTHLY, CADENCE_ONCE),
    )


def _new_id() -> str:
    """A unique identifier for a new record.

    The timestamp alone was not enough. Windows' clock granularity can be
    coarse enough that two records created in quick succession get the same
    stamp, and a duplicate id here is not cosmetic: payments are matched to
    subscriptions by id, so marking one paid marked its twin, and deleting one
    deleted both. Continuous integration caught this where a faster local clock
    hid it.

    The timestamp is kept as a prefix because it makes ids readable and roughly
    ordered by creation; the random suffix is what makes them unique.
    """
    return datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + secrets.token_hex(4)


def _migrate_card_columns(connection: sqlite3.Connection) -> None:
    """Add `kind` to card tables written before bank accounts existed.

    Everything already stored was a credit card, which is the column default,
    so nothing needs back-filling beyond the default itself.
    """
    try:
        existing = {row[1] for row in connection.execute("PRAGMA table_info(cards)").fetchall()}
    except sqlite3.OperationalError:
        return
    if not existing:
        return
    if "kind" not in existing:
        connection.execute("ALTER TABLE cards ADD COLUMN kind TEXT NOT NULL DEFAULT 'card'")


def create_schema(data_file: Path) -> None:
    data_file.parent.mkdir(parents=True, exist_ok=True)
    with _connect(data_file) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                amount REAL,
                date TEXT NOT NULL,
                account TEXT NOT NULL,
                category TEXT NOT NULL,
                recurring_monthly INTEGER NOT NULL DEFAULT 0,
                due_day INTEGER,
                expense_type TEXT NOT NULL DEFAULT 'Fixed',
                color TEXT NOT NULL DEFAULT '#f4a261',
                cadence TEXT,
                ends_on TEXT,
                paid_with TEXT,
                paused INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _migrate_expense_columns(connection)
        _migrate_card_columns(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS expense_payments (
                expense_id TEXT NOT NULL,
                paid_year INTEGER NOT NULL,
                paid_month INTEGER NOT NULL,
                paid_on TEXT NOT NULL DEFAULT (DATE('now')),
                PRIMARY KEY (expense_id, paid_year, paid_month),
                FOREIGN KEY (expense_id) REFERENCES expenses (id) ON DELETE CASCADE
            )
            """
        )
        # Cards are deliberately not expenses. Paying a card settles purchases
        # that were already recorded, so counting the payment as spending would
        # count the same money twice. They live in their own tables and never
        # reach any spending total.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                due_day INTEGER,
                color TEXT NOT NULL DEFAULT '#5b8ac7',
                notes TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'card'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS card_payments (
                card_id TEXT NOT NULL,
                paid_year INTEGER NOT NULL,
                paid_month INTEGER NOT NULL,
                amount REAL NOT NULL,
                paid_on TEXT NOT NULL DEFAULT (DATE('now')),
                PRIMARY KEY (card_id, paid_year, paid_month),
                FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders_sent (
                kind TEXT NOT NULL,
                record_id TEXT NOT NULL,
                due_on TEXT NOT NULL,
                sent_on TEXT NOT NULL DEFAULT (DATE('now')),
                PRIMARY KEY (kind, record_id, due_on)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_credentials (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                iterations INTEGER NOT NULL CHECK (iterations > 0),
                created_at TEXT NOT NULL DEFAULT (DATETIME('now'))
            )
            """
        )


def has_local_credentials(data_file: Path) -> bool:
    try:
        with _connect(data_file) as connection:
            result = connection.execute("SELECT COUNT(*) FROM app_credentials").fetchone()
        return bool(result and result[0] > 0)
    except sqlite3.OperationalError:
        return False


def get_stored_credentials(data_file: Path) -> tuple[str, str, str, int] | None:
    try:
        with _connect(data_file) as connection:
            row = connection.execute(
                """
                SELECT username, password_hash, password_salt, iterations
                FROM app_credentials
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.OperationalError:
        return None

    if row is None:
        return None
    return row[0], row[1], row[2], int(row[3])


def save_credentials(data_file: Path, username: str, password_hash: str, password_salt: str, iterations: int) -> None:
    create_schema(data_file)
    with _connect(data_file) as connection:
        connection.execute(
            """
            INSERT INTO app_credentials (username, password_hash, password_salt, iterations)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                password_salt = excluded.password_salt,
                iterations = excluded.iterations
            """
        , (username, password_hash, password_salt, iterations)
        )


def clear_credentials(data_file: Path) -> None:
    if not data_file.exists():
        return
    with _connect(data_file) as connection:
        try:
            connection.execute("DELETE FROM app_credentials")
        except sqlite3.OperationalError:
            return


def _read_legacy_json(json_file: Path) -> List[Expense]:
    if not json_file.exists():
        return []
    try:
        with json_file.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []

    expenses: List[Expense] = []
    for item in raw:
        expenses.append(
            Expense(
                id=item["id"],
                description=item["description"],
                amount=None if item.get("amount") is None else round(float(item["amount"]), 2),
                date=item.get("date", ""),
                account=item.get("account", "Main"),
                category=item.get("category", "General"),
                recurring_monthly=bool(item.get("recurring_monthly", False)),
                due_day=item.get("due_day"),
                cadence=item.get("cadence", ""),
                ends_on=item.get("ends_on"),
                expense_type=item.get("expense_type", "Fixed"),
                color=item.get("color", "#f4a261"),
            )
        )
    return expenses


def _to_dict(expense: Expense) -> dict[str, object]:
    return {
        "id": expense.id,
        "description": expense.description,
        "amount": expense.amount,
        "date": expense.date,
        "account": expense.account,
        "category": expense.category,
        "recurring_monthly": int(expense.recurring_monthly),
        "due_day": expense.due_day,
        "expense_type": expense.expense_type,
        "color": expense.color,
        "cadence": expense.cadence,
        "ends_on": expense.ends_on,
        "paid_with": expense.paid_with,
        "paused": bool(expense.paused),
    }


def _upsert_expenses(connection: sqlite3.Connection, expenses: List[Expense]) -> None:
    data = [_to_dict(item) for item in expenses]
    if data:
        # ON CONFLICT ... DO UPDATE rather than INSERT OR REPLACE: the latter
        # deletes the conflicting row first, and expense_payments cascades on
        # delete, so replacing a row would silently wipe its paid history.
        connection.executemany(
            """
            INSERT INTO expenses (
                id, description, amount, date, account, category,
                recurring_monthly, due_day, expense_type, color, cadence, ends_on, paid_with,
                paused
            ) VALUES (
                :id, :description, :amount, :date, :account, :category,
                :recurring_monthly, :due_day, :expense_type, :color, :cadence, :ends_on,
                :paid_with, :paused
            )
            ON CONFLICT(id) DO UPDATE SET
                description = excluded.description,
                amount = excluded.amount,
                date = excluded.date,
                account = excluded.account,
                category = excluded.category,
                recurring_monthly = excluded.recurring_monthly,
                due_day = excluded.due_day,
                expense_type = excluded.expense_type,
                color = excluded.color,
                cadence = excluded.cadence,
                ends_on = excluded.ends_on,
                paid_with = excluded.paid_with,
                paused = excluded.paused
            """,
            data,
        )


def _replace_all_expenses_in_db(data_file: Path, expenses: List[Expense]) -> None:
    with _connect(data_file) as connection:
        _upsert_expenses(connection, expenses)


def _existing_expense_ids_in_db(data_file: Path) -> List[str]:
    with _connect(data_file) as connection:
        rows = connection.execute("SELECT id FROM expenses").fetchall()
    return [row[0] for row in rows]


def _ensure_db_initialized_and_seeded(data_file: Path) -> None:
    create_schema(data_file)
    with _connect(data_file) as connection:
        total = connection.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        migration_complete = connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'legacy_json_migrated'"
        ).fetchone()

    if migration_complete is None and total == 0:
        legacy_expenses = _read_legacy_json(_json_fallback_path(data_file))
        if legacy_expenses:
            _replace_all_expenses_in_db(data_file, legacy_expenses)

    if migration_complete is None:
        with _connect(data_file) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO app_metadata (key, value) VALUES ('legacy_json_migrated', '1')"
            )


def load_expenses(data_file: Path) -> List[Expense]:
    if data_file.suffix.lower() == ".json":
        return _read_legacy_json(data_file)

    _ensure_db_initialized_and_seeded(data_file)
    with _connect(data_file) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, description, amount, date, account, category, recurring_monthly,
                   due_day, expense_type, color, cadence, ends_on, paid_with, paused
            FROM expenses
            ORDER BY date, description
            """
        ).fetchall()

    return [
        Expense(
            id=row["id"],
            description=row["description"],
            amount=None if row["amount"] is None else float(row["amount"]),
            date=row["date"] or "",
            account=row["account"] or "Main",
            category=row["category"] or "General",
            recurring_monthly=bool(row["recurring_monthly"]),
            due_day=row["due_day"] if row["due_day"] is not None else None,
            expense_type=row["expense_type"] or "Fixed",
            color=row["color"] or "#f4a261",
            cadence=row["cadence"] or "",
            ends_on=row["ends_on"],
            paid_with=row["paid_with"],
            paused=bool(row["paused"]),
        )
        for row in rows
    ]


def save_expenses(data_file: Path, expenses: List[Expense]) -> None:
    if data_file.suffix.lower() == ".json":
        data_file.parent.mkdir(parents=True, exist_ok=True)
        with data_file.open("w", encoding="utf-8") as handle:
            json.dump([asdict(item) for item in expenses], handle, indent=2)
        return

    _ensure_db_initialized_and_seeded(data_file)
    ids = [expense.id for expense in expenses]
    with _connect(data_file) as connection:
        connection.execute("DELETE FROM expense_payments WHERE expense_id NOT IN (SELECT id FROM expenses)")

        if ids:
            connection.execute(
                f"DELETE FROM expenses WHERE id NOT IN ({','.join('?' for _ in ids)})",
                ids,
            )
        else:
            connection.execute("DELETE FROM expenses")

        _upsert_expenses(connection, expenses)


def add_expense(data_file: Path, expense: Expense) -> None:
    if data_file.suffix.lower() == ".json":
        expenses = load_expenses(data_file)
        expenses.append(expense)
        save_expenses(data_file, expenses)
        return

    _ensure_db_initialized_and_seeded(data_file)
    with _connect(data_file) as connection:
        payload = _to_dict(expense)
        connection.execute(
            """
            INSERT INTO expenses (
                id, description, amount, date, account, category, recurring_monthly,
                due_day, expense_type, color, cadence, ends_on, paid_with, paused
            ) VALUES (
                :id, :description, :amount, :date, :account, :category, :recurring_monthly,
                :due_day, :expense_type, :color, :cadence, :ends_on, :paid_with, :paused
            )
            """,
            payload,
        )


def update_expense(data_file: Path, expense: Expense) -> None:
    """Change an existing subscription in place, keeping its paid history.

    The id is deliberately never touched: expense_payments references it, so
    rewriting the row under a new id — or deleting and re-adding — would lose
    every month the user had already marked as paid.
    """
    if data_file.suffix.lower() == ".json":
        expenses = [expense if item.id == expense.id else item for item in load_expenses(data_file)]
        save_expenses(data_file, expenses)
        return

    _ensure_db_initialized_and_seeded(data_file)
    with _connect(data_file) as connection:
        connection.execute(
            """
            UPDATE expenses SET
                description = :description,
                amount = :amount,
                date = :date,
                account = :account,
                category = :category,
                recurring_monthly = :recurring_monthly,
                due_day = :due_day,
                expense_type = :expense_type,
                color = :color,
                cadence = :cadence,
                ends_on = :ends_on,
                paid_with = :paid_with,
                paused = :paused
            WHERE id = :id
            """,
            _to_dict(expense),
        )


def delete_expense(data_file: Path, expense_id: str) -> None:
    if data_file.suffix.lower() == ".json":
        expenses = [item for item in load_expenses(data_file) if item.id != expense_id]
        save_expenses(data_file, expenses)
        return

    if not data_file.exists():
        return
    with _connect(data_file) as connection:
        connection.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


# --- cards ---------------------------------------------------------------
#
# Everything below is kept apart from expenses on purpose. No function here
# feeds a spending total, and nothing in the expense side reads these tables.


def create_card(
    name: str,
    due_day: Optional[int] = None,
    color: str = "#5b8ac7",
    notes: str = "",
    card_id: Optional[str] = None,
    kind: str = KIND_CARD,
) -> Card:
    """A card needs a due day; a bank account has none and must not carry one."""
    if kind not in PAYMENT_KINDS:
        raise ValueError(f"unknown payment source kind {kind!r}")

    cleaned = name.strip()
    if not cleaned:
        raise ValueError("a payment source needs a name")

    if kind == KIND_BANK:
        day = None
    else:
        try:
            day = int(due_day)
        except (TypeError, ValueError):
            raise ValueError("a card needs a due day between 1 and 31")
        if not 1 <= day <= 31:
            raise ValueError("a card needs a due day between 1 and 31")

    return Card(
        id=card_id or _new_id(),
        name=cleaned,
        due_day=day,
        color=color or "#5b8ac7",
        notes=notes.strip(),
        kind=kind,
    )


def load_cards(data_file: Path) -> List[Card]:
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return []
    try:
        with _connect(data_file) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT id, name, due_day, color, notes, kind FROM cards ORDER BY kind DESC, due_day, name"
            ).fetchall()
    except sqlite3.OperationalError:
        # A database written before cards existed.
        return []
    return [
        Card(
            id=row["id"],
            name=row["name"],
            due_day=row["due_day"],
            color=row["color"] or "#5b8ac7",
            notes=row["notes"] or "",
            kind=row["kind"] or KIND_CARD,
        )
        for row in rows
    ]


def save_card(data_file: Path, card: Card) -> None:
    """Insert or update, without disturbing the payments already recorded.

    Uses ON CONFLICT rather than INSERT OR REPLACE: REPLACE deletes the row
    first, which would cascade and wipe every payment against the card.
    """
    if data_file.suffix.lower() == ".json":
        return
    create_schema(data_file)
    with _connect(data_file) as connection:
        connection.execute(
            """
            INSERT INTO cards (id, name, due_day, color, notes, kind)
            VALUES (:id, :name, :due_day, :color, :notes, :kind)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                due_day = excluded.due_day,
                color = excluded.color,
                notes = excluded.notes,
                kind = excluded.kind
            """,
            asdict(card),
        )


def delete_card(data_file: Path, card_id: str) -> None:
    """Remove a payment source, and unlink anything charged to it.

    Subscriptions keep a card id rather than a copy of its name, so deleting a
    source would otherwise leave them pointing at nothing. They are cleared
    rather than deleted: the subscription still exists and still bills, it just
    no longer says where from.
    """
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return
    with _connect(data_file) as connection:
        connection.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        try:
            connection.execute(
                "UPDATE expenses SET paid_with = NULL WHERE paid_with = ?", (card_id,)
            )
        except sqlite3.OperationalError:
            # A database written before the link existed.
            pass


def card_due_date(card: Card, year: int, month: int) -> Optional[date]:
    """The card's due date in a month, clamped to months that are short.

    None for a bank account, which has no bill of its own and so no due date.
    """
    if card.due_day is None:
        return None
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(card.due_day, last_day))


def set_card_payment(
    data_file: Path, card_id: str, year: int, month: int, amount: Optional[float]
) -> None:
    """Record what was actually paid. `None` clears the month."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return
    with _connect(data_file) as connection:
        if amount is None:
            connection.execute(
                "DELETE FROM card_payments WHERE card_id = ? AND paid_year = ? AND paid_month = ?",
                (card_id, year, month),
            )
            return
        connection.execute(
            """
            INSERT INTO card_payments (card_id, paid_year, paid_month, amount, paid_on)
            VALUES (?, ?, ?, ?, DATE('now'))
            ON CONFLICT(card_id, paid_year, paid_month) DO UPDATE SET
                amount = excluded.amount,
                paid_on = DATE('now')
            """,
            (card_id, year, month, round(float(amount), 2)),
        )


def get_card_payments(data_file: Path, year: int, month: int) -> dict:
    """What was paid against each card in one month, keyed by card id."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return {}
    try:
        with _connect(data_file) as connection:
            rows = connection.execute(
                "SELECT card_id, amount FROM card_payments WHERE paid_year = ? AND paid_month = ?",
                (year, month),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: row[1] for row in rows}


def get_card_payment_history(data_file: Path, card_id: str, limit: int = 12) -> List[tuple]:
    """Recent payments as (year, month, amount), newest first."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return []
    try:
        with _connect(data_file) as connection:
            rows = connection.execute(
                """
                SELECT paid_year, paid_month, amount FROM card_payments
                WHERE card_id = ?
                ORDER BY paid_year DESC, paid_month DESC
                LIMIT ?
                """,
                (card_id, limit),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(row[0], row[1], row[2]) for row in rows]


def cards_only(cards: List[Card]) -> List[Card]:
    """Just the credit cards. Bank accounts have no bill and no due date."""
    return [card for card in cards if card.is_card]


def find_card(cards: List[Card], card_id: Optional[str]) -> Optional[Card]:
    if not card_id:
        return None
    return next((card for card in cards if card.id == card_id), None)


def payment_source_name(cards: List[Card], card_id: Optional[str]) -> str:
    """A subscription's payment source, for display. Empty when unset."""
    card = find_card(cards, card_id)
    return card.name if card else ""


def expenses_charged_to(expenses: List[Expense], card_id: str) -> List[Expense]:
    """Every subscription pointing at one payment source, still-running first."""
    matching = [expense for expense in expenses if expense.paid_with == card_id]
    today = date.today()
    return sorted(
        matching,
        key=lambda item: (next_occurrence(item, today) is None, item.description.lower()),
    )


def subscription_run_rate_for_source(expenses: List[Expense], card_id: str) -> float:
    """What the subscriptions on one payment source cost per month.

    Uses the same per-cadence normalisation as the headline run rate, so a
    yearly renewal charged to a card counts as a twelfth rather than landing
    whole in one month.
    """
    return round(
        sum(monthly_equivalent(expense) for expense in expenses_charged_to(expenses, card_id)),
        2,
    )


# --- money -----------------------------------------------------------------
#
# Every amount on screen and in every export goes through `money()`. It reads a
# module-level setting rather than taking the currency as an argument, because
# the alternative is threading it through roughly thirty call sites that have no
# other reason to know about it. `set_currency` is called once at startup and
# again when it is changed.

CURRENCY_SETTING = "currency"

# A short list rather than the ISO 4217 catalogue. Someone whose currency is
# missing can type their own symbol, which covers everyone without presenting
# 180 options to choose between.
#
# `space` is whether the symbol needs separating from the digits: "$22.99" reads
# correctly, "Rs.1,200" does not.
CURRENCIES = (
    ("USD", "$", False, "US dollar"),
    ("NPR", "Rs.", True, "Nepalese rupee"),
    ("INR", "₹", False, "Indian rupee"),
    ("GBP", "£", False, "Pound sterling"),
    ("EUR", "€", False, "Euro"),
    ("AUD", "A$", False, "Australian dollar"),
    ("CAD", "C$", False, "Canadian dollar"),
    ("JPY", "¥", False, "Japanese yen"),
    ("AED", "AED", True, "UAE dirham"),
    ("SGD", "S$", False, "Singapore dollar"),
)

DEFAULT_CURRENCY = "$"

_currency_symbol = DEFAULT_CURRENCY
_currency_space = False


def set_currency(symbol: str, space: Optional[bool] = None) -> None:
    """Choose the symbol every amount is shown with.

    When `space` is not given it is inferred: a symbol made of letters needs
    separating from the digits, a glyph does not.
    """
    global _currency_symbol, _currency_space
    cleaned = (symbol or "").strip() or DEFAULT_CURRENCY
    _currency_symbol = cleaned
    if space is None:
        known = {code_symbol: needs for _code, code_symbol, needs, _name in CURRENCIES}
        space = known.get(cleaned, any(character.isalpha() for character in cleaned))
    _currency_space = bool(space)


def current_currency() -> str:
    return _currency_symbol


def reset_currency() -> None:
    """Back to the default. Exists so tests are not order-dependent."""
    set_currency(DEFAULT_CURRENCY, False)


def money(value: Optional[float], places: int = 2) -> str:
    """One amount, formatted the way this installation shows money."""
    if value is None:
        return ""
    figure = format(value, "," + "." + str(places) + "f")
    return _currency_symbol + (" " if _currency_space else "") + figure


def load_currency(data_file: Path) -> str:
    """Apply the stored choice. Called once, at startup."""
    symbol = get_setting(data_file, CURRENCY_SETTING, DEFAULT_CURRENCY) or DEFAULT_CURRENCY
    set_currency(symbol)
    return symbol


def save_currency(data_file: Path, symbol: str) -> None:
    set_setting(data_file, CURRENCY_SETTING, (symbol or "").strip() or DEFAULT_CURRENCY)
    set_currency(symbol)


def get_setting(data_file: Path, key: str, default: str = "") -> str:
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return default
    try:
        with _connect(data_file) as connection:
            row = connection.execute(
                "SELECT value FROM app_metadata WHERE key = ?", (key,)
            ).fetchone()
    except sqlite3.OperationalError:
        return default
    return row[0] if row else default


def set_setting(data_file: Path, key: str, value: str) -> None:
    if data_file.suffix.lower() == ".json":
        return
    create_schema(data_file)
    with _connect(data_file) as connection:
        connection.execute(
            "INSERT INTO app_metadata (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


REMINDERS_ENABLED = "reminders_enabled"
REMINDER_DAYS = "reminder_days"
REMINDER_TIME = "reminder_time"
DEFAULT_REMINDER_DAYS = 3


def reminders_are_on(data_file: Path) -> bool:
    return get_setting(data_file, REMINDERS_ENABLED, "0") == "1"


def reminder_days(data_file: Path) -> int:
    """How many days of warning. Falls back rather than failing on bad data."""
    try:
        days = int(get_setting(data_file, REMINDER_DAYS, str(DEFAULT_REMINDER_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_REMINDER_DAYS
    return days if 0 <= days <= 30 else DEFAULT_REMINDER_DAYS


# --- reminders -----------------------------------------------------------


@dataclass
class Reminder:
    """One thing worth telling someone about before it happens.

    Deliberately free of any notification machinery: this says what is coming,
    and something else decides how to say it. That keeps the interesting part
    testable without a desktop.
    """

    kind: str          # "subscription" or "card"
    record_id: str
    title: str
    due: date
    amount: Optional[float] = None
    source: str = ""

    def when(self, today: date) -> str:
        days = (self.due - today).days
        if days == 0:
            return "today"
        if days == 1:
            return "tomorrow"
        return "in " + str(days) + " days"

    def headline(self) -> str:
        return self.title

    def detail(self, today: date) -> str:
        """The sentence under the heading, naming the amount and the source."""
        when = self.when(today)
        on = self.due.strftime("%a %d %b")

        if self.kind == "card":
            # A card's amount is never known in advance, so promising one would
            # be a lie. The date is the whole point.
            where = " for " + self.source if self.source else ""
            return "Payment" + where + " is due " + when + ", on " + on + "."

        amount = "an unknown amount" if self.amount is None else money(self.amount)
        where = " to " + self.source if self.source else ""
        return "Charging " + amount + where + " " + when + ", on " + on + "."


def due_reminders(
    expenses: List[Expense],
    cards: List[Card],
    today: date,
    days_ahead: int = 3,
) -> List[Reminder]:
    """Everything falling due exactly `days_ahead` days from `today`.

    Exactly, not within, so a subscription is announced once rather than on
    each of the three days before it bills.
    """
    if days_ahead < 0:
        raise ValueError("days_ahead cannot be negative")

    target = today + timedelta(days=days_ahead)
    reminders: List[Reminder] = []

    for expense in expenses:
        if occurs_on(expense, target):
            reminders.append(
                Reminder(
                    kind="subscription",
                    record_id=expense.id,
                    title=expense.description,
                    due=target,
                    amount=expense.amount,
                    source=payment_source_name(cards, expense.paid_with),
                )
            )

    for card in cards_only(cards):
        if card_due_date(card, target.year, target.month) == target:
            reminders.append(
                Reminder(kind="card", record_id=card.id, title=card.name, due=target)
            )

    reminders.sort(key=lambda item: (item.kind, item.title.lower()))
    return reminders


def already_reminded(data_file: Path, reminder: Reminder) -> bool:
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return False
    try:
        with _connect(data_file) as connection:
            row = connection.execute(
                "SELECT 1 FROM reminders_sent WHERE kind = ? AND record_id = ? AND due_on = ?",
                (reminder.kind, reminder.record_id, reminder.due.isoformat()),
            ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def mark_reminded(data_file: Path, reminder: Reminder) -> None:
    """Remember that this was announced, so it is not announced again."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return
    with _connect(data_file) as connection:
        connection.execute(
            """
            INSERT INTO reminders_sent (kind, record_id, due_on, sent_on)
            VALUES (?, ?, ?, DATE('now'))
            ON CONFLICT(kind, record_id, due_on) DO NOTHING
            """,
            (reminder.kind, reminder.record_id, reminder.due.isoformat()),
        )


def pending_reminders(
    data_file: Path,
    expenses: List[Expense],
    cards: List[Card],
    today: date,
    days_ahead: int = 3,
) -> List[Reminder]:
    """Reminders that are due and have not been given yet."""
    return [
        reminder
        for reminder in due_reminders(expenses, cards, today, days_ahead)
        if not already_reminded(data_file, reminder)
    ]


def forget_old_reminders(data_file: Path, before: date) -> None:
    """Drop records for dates long past, so the table cannot grow forever."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return
    with _connect(data_file) as connection:
        connection.execute("DELETE FROM reminders_sent WHERE due_on < ?", (before.isoformat(),))


def get_card_year_totals(data_file: Path, year: int) -> dict:
    """What was paid against each card across one year, keyed by card id."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return {}
    try:
        with _connect(data_file) as connection:
            rows = connection.execute(
                """
                SELECT card_id, SUM(amount) FROM card_payments
                WHERE paid_year = ?
                GROUP BY card_id
                """,
                (year,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: round(row[1] or 0.0, 2) for row in rows}


def get_card_payments_for_year(data_file: Path, card_id: str, year: int) -> dict:
    """One card's twelve months, keyed by month number. Missing months absent."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return {}
    try:
        with _connect(data_file) as connection:
            rows = connection.execute(
                "SELECT paid_month, amount FROM card_payments WHERE card_id = ? AND paid_year = ?",
                (card_id, year),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: row[1] for row in rows}


def get_card_years(data_file: Path) -> List[int]:
    """Every year that has at least one recorded payment, newest first."""
    if data_file.suffix.lower() == ".json" or not data_file.exists():
        return []
    try:
        with _connect(data_file) as connection:
            rows = connection.execute(
                "SELECT DISTINCT paid_year FROM card_payments ORDER BY paid_year DESC"
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [row[0] for row in rows]


def get_cards_due_in_month(cards: List[Card], year: int, month: int) -> dict:
    """Cards falling due in a month, keyed by ISO date, for the calendar."""
    by_day: dict = {}
    for card in cards_only(cards):
        due = card_due_date(card, year, month)
        if due is None:
            continue
        by_day.setdefault(due.isoformat(), []).append(card)
    return by_day


def get_cards_due_between(cards: List[Card], start: date, days: int = 14) -> List[tuple]:
    """Card due dates in the next `days` days, as (date, card) pairs."""
    upcoming: List[tuple] = []
    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        for card in cards_only(cards):
            if card_due_date(card, day.year, day.month) == day:
                upcoming.append((day, card))
    return sorted(upcoming, key=lambda pair: (pair[0], pair[1].name.lower()))


def wrap_text(text: str, width: int = 18) -> str:
    if not text:
        return ""
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False))


def create_expense(
    description: str,
    amount: Optional[float],
    expense_date: str,
    account: str = "Main",
    category: str = "General",
    recurring_monthly: bool = False,
    due_day: Optional[int] = None,
    expense_type: str = "Fixed",
    color: str = "#f4a261",
    cadence: str = "",
    ends_on: Optional[str] = None,
    expense_id: Optional[str] = None,
    paid_with: Optional[str] = None,
    paused: bool = False,
) -> Expense:
    normalized_amount = None if amount is None else round(float(amount), 2)
    normalized_date = expense_date or ""
    if due_day is not None:
        try:
            due_day = int(due_day)
        except (TypeError, ValueError):
            due_day = None

    if normalized_amount is None and due_day is None and normalized_date:
        try:
            parsed_day = int(normalized_date.split("-")[-1])
            due_day = parsed_day
        except ValueError:
            due_day = None

    return Expense(
        id=expense_id or _new_id(),
        description=description.strip(),
        amount=normalized_amount,
        date=normalized_date,
        account=account.strip() or "Main",
        category=category.strip() or "General",
        recurring_monthly=bool(recurring_monthly),
        due_day=due_day,
        expense_type=expense_type.strip() or "Fixed",
        color=color,
        cadence=cadence,
        ends_on=ends_on,
        paid_with=paid_with or None,
        paused=bool(paused),
    )


def _parse_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _day_in_month(year: int, month: int, day: int) -> date:
    """Clamp a day-of-month to a real date, so a 31st bills on the 30th in June."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _billing_day(expense: Expense) -> int:
    if expense.due_day is not None and 1 <= expense.due_day <= 31:
        return expense.due_day
    start = _parse_iso(expense.date)
    return start.day if start else 1


def occurs_on(expense: Expense, day: date) -> bool:
    """Does this subscription bill on the given day?

    The stored `date` is the first billing date and `ends_on` the last, so a
    subscription never appears before it started or after it was cancelled.
    """
    # Everything else follows from here: the calendar, month totals, the
    # upcoming list and the reminders all ask this one question, so pausing is
    # answered once rather than in nine places.
    if expense.paused:
        return False

    start = _parse_iso(expense.date)
    if start is None or day < start:
        return False

    end = _parse_iso(expense.ends_on)
    if end is not None and day > end:
        return False

    cadence = expense.cadence
    if cadence == CADENCE_ONCE:
        return day == start
    if cadence == CADENCE_WEEKLY:
        return (day - start).days % 7 == 0

    if day != _day_in_month(day.year, day.month, _billing_day(expense)):
        return False

    if cadence == CADENCE_MONTHLY:
        return True
    months_apart = (day.year - start.year) * 12 + (day.month - start.month)
    if cadence == CADENCE_QUARTERLY:
        return months_apart % 3 == 0
    if cadence == CADENCE_YEARLY:
        return months_apart % 12 == 0
    return False


def occurrences_in_month(expense: Expense, year: int, month: int) -> List[date]:
    last_day = calendar.monthrange(year, month)[1]
    return [
        candidate
        for candidate in (date(year, month, number) for number in range(1, last_day + 1))
        if occurs_on(expense, candidate)
    ]


def _is_in_target_month(expense: Expense, year: int, month: int) -> bool:
    return bool(occurrences_in_month(expense, year, month))


def get_expenses_for_month(expenses: List[Expense], year: int, month: int) -> List[Expense]:
    month_expenses = [expense for expense in expenses if _is_in_target_month(expense, year, month)]
    return sorted(
        month_expenses,
        key=lambda item: (
            item.date or "",
            item.due_day if item.due_day is not None else 0,
            item.description.lower(),
        ),
    )


def get_total_for_month(expenses: List[Expense], year: int, month: int) -> float:
    # A weekly subscription bills several times a month, so the month's cost is
    # the amount multiplied by how often it actually falls due.
    total = 0.0
    for expense in get_expenses_for_month(expenses, year, month):
        if expense.amount is not None:
            total += expense.amount * len(occurrences_in_month(expense, year, month))
    return round(total, 2)


def get_yearly_total(expenses: List[Expense], year: int) -> float:
    return round(sum(get_total_for_month(expenses, year, month) for month in range(1, 13)), 2)


def next_occurrence(expense: Expense, start: date, horizon_days: int = 800):
    """The first day on or after `start` that this subscription bills.

    Returns None when nothing is left, which is the case for a one-off already in
    the past or a subscription whose end date has gone by. The horizon covers
    slightly over two years so that an annual renewal is always found.
    """
    end = _parse_iso(expense.ends_on)
    for offset in range(horizon_days + 1):
        day = start + timedelta(days=offset)
        if end is not None and day > end:
            return None
        if occurs_on(expense, day):
            return day
    return None


GROUP_FIELDS = ("category",)


def get_totals_by(
    expenses: List[Expense], year: int, month: int, field: str = "category",
) -> List[tuple]:
    """Spend for one month grouped by `field`, largest first.

    Uses the same occurrence counting as get_total_for_month, so a weekly
    subscription contributes every time it falls due rather than once.
    """
    if field not in GROUP_FIELDS:
        raise ValueError(f"cannot group by {field!r}; expected one of {GROUP_FIELDS}")

    totals: dict = {}
    for expense in get_expenses_for_month(expenses, year, month):
        if expense.amount is None:
            continue
        occurrences = len(occurrences_in_month(expense, year, month))
        name = getattr(expense, field) or "Uncategorised"
        totals[name] = totals.get(name, 0.0) + expense.amount * occurrences

    ranked = [(name, round(value, 2)) for name, value in totals.items()]
    ranked.sort(key=lambda item: (-item[1], item[0].lower()))
    return ranked


def get_source_totals(
    expenses: List[Expense],
    cards: List[Card],
    year: int,
    month: int,
    unassigned: str = "Not set",
) -> List[tuple]:
    """One month's spending grouped by which card or account it is charged to.

    This is deliberately built from the **subscriptions**, not from what was
    paid to each card. A card payment settles purchases that are already
    recorded here, so charting those as spending would count the same money
    twice — the rule the cards half of the application exists to keep. What is
    on this chart is real spending, attributed to where it comes out.

    Subscriptions with no payment source are gathered under `unassigned` rather
    than dropped, so the shares always add up to the month's total.
    """
    totals: dict = {}
    for expense in get_expenses_for_month(expenses, year, month):
        if expense.amount is None:
            continue
        occurrences = len(occurrences_in_month(expense, year, month))
        name = payment_source_name(cards, expense.paid_with) or unassigned
        totals[name] = totals.get(name, 0.0) + expense.amount * occurrences

    ranked = [(name, round(value, 2)) for name, value in totals.items()]
    ranked.sort(key=lambda item: (-item[1], item[0].lower()))
    return ranked


def get_category_totals(expenses: List[Expense], year: int, month: int) -> List[tuple]:
    return get_totals_by(expenses, year, month, "category")


def get_monthly_totals(expenses: List[Expense], year: int) -> List[float]:
    """Twelve monthly totals for `year`, January first."""
    return [get_total_for_month(expenses, year, month) for month in range(1, 13)]


# How many times a cadence bills in an average month. Weekly is 52/12 rather
# than 4, because four weeks is not a month.
MONTHLY_EQUIVALENT = {
    CADENCE_WEEKLY: 52 / 12,
    CADENCE_MONTHLY: 1.0,
    CADENCE_QUARTERLY: 1 / 3,
    CADENCE_YEARLY: 1 / 12,
}

# Cadences that do not fall due every month, and so make one month's total
# jump. A one-off is included: it spikes a month exactly once.
IRREGULAR_CADENCES = (CADENCE_ONCE, CADENCE_QUARTERLY, CADENCE_YEARLY)

IRREGULAR_LABELS = {
    CADENCE_ONCE: "one-off",
    CADENCE_QUARTERLY: "quarterly",
    CADENCE_YEARLY: "yearly",
}


def monthly_equivalent(expense: Expense) -> float:
    """What one subscription costs in an average month.

    A $70 yearly subscription is $5.83 a month by this measure. That is a
    different question from what leaves the account in the month it bills,
    which is $70 and is what get_total_for_month reports. Both are true; this
    one answers "what do my subscriptions cost me to run".

    A one-off has no monthly cost, because it is not a commitment that repeats.
    """
    if expense.amount is None or expense.paused:
        return 0.0
    factor = MONTHLY_EQUIVALENT.get(expense.cadence)
    if factor is None:
        return 0.0
    return expense.amount * factor


def is_still_running(expense: Expense, today: Optional[date] = None) -> bool:
    """True unless the subscription has an end date that has already passed."""
    if expense.cadence == CADENCE_ONCE:
        return False
    if not expense.ends_on:
        return True
    end = _parse_iso(expense.ends_on)
    if end is None:
        return True
    return end >= (today or date.today())


def get_monthly_run_rate(expenses: List[Expense], today: Optional[date] = None) -> float:
    """What the subscriptions still running cost per month, on average.

    Deliberately a run rate rather than the year's total divided by twelve:
    dividing the year undercounts anything started recently, and changes every
    time the calendar rolls over. This answers "from here on, what am I
    committed to each month".
    """
    return round(
        sum(monthly_equivalent(expense) for expense in expenses if is_still_running(expense, today)),
        2,
    )


def get_irregular_total_for_month(expenses: List[Expense], year: int, month: int) -> tuple:
    """The part of a month's total that will not be there every month.

    Returns (amount, labels) so the interface can say *why* a month is high.
    """
    total = 0.0
    kinds = set()
    for expense in get_expenses_for_month(expenses, year, month):
        if expense.amount is None or expense.cadence not in IRREGULAR_CADENCES:
            continue
        occurrences = len(occurrences_in_month(expense, year, month))
        if not occurrences:
            continue
        total += expense.amount * occurrences
        kinds.add(expense.cadence)
    ordered = [IRREGULAR_LABELS[name] for name in IRREGULAR_CADENCES if name in kinds]
    return round(total, 2), ordered


def get_paid_expense_ids(data_file: Path, year: int, month: int) -> Set[str]:
    if data_file.suffix.lower() == ".json":
        return set()

    if not data_file.exists():
        return set()

    query = "SELECT expense_id FROM expense_payments WHERE paid_year = ? AND paid_month = ?"
    with _connect(data_file) as connection:
        rows = connection.execute(query, (year, month)).fetchall()
    return {row[0] for row in rows}


def get_paid_total_for_month(
    expenses: List[Expense], paid_expense_ids: Set[str], year: int, month: int
) -> float:
    total = 0.0
    for expense in get_expenses_for_month(expenses, year, month):
        if expense.amount is not None and expense.id in paid_expense_ids:
            total += expense.amount * len(occurrences_in_month(expense, year, month))
    return round(total, 2)


def set_expense_paid(data_file: Path, expense_id: str, year: int, month: int, paid: bool) -> None:
    if data_file.suffix.lower() == ".json":
        return

    if not data_file.exists():
        return

    with _connect(data_file) as connection:
        if paid:
            connection.execute(
                """
                INSERT OR REPLACE INTO expense_payments (expense_id, paid_year, paid_month, paid_on)
                VALUES (?, ?, ?, DATE('now'))
                """,
                (expense_id, year, month),
            )
        else:
            connection.execute(
                "DELETE FROM expense_payments WHERE expense_id = ? AND paid_year = ? AND paid_month = ?",
                (expense_id, year, month),
            )


def get_expenses_for_day(expenses: List[Expense], day: date) -> List[Expense]:
    unique_by_id: dict[str, Expense] = {}
    for expense in expenses:
        if occurs_on(expense, day):
            unique_by_id[expense.id] = expense

    return sorted(unique_by_id.values(), key=lambda item: item.description.lower())


def get_expenses_by_day(expenses: List[Expense], year: int, month: int) -> dict[str, List[Expense]]:
    by_day: dict[str, List[Expense]] = {}
    for expense in get_expenses_for_month(expenses, year, month):
        for occurrence in occurrences_in_month(expense, year, month):
            by_day.setdefault(occurrence.isoformat(), []).append(expense)
    return by_day


def get_upcoming(expenses: List[Expense], start: date, days: int = 7) -> List[tuple]:
    """Every billing date in the next `days` days, as (date, expense) pairs."""
    upcoming: List[tuple] = []
    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        for expense in get_expenses_for_day(expenses, day):
            upcoming.append((day, expense))
    return upcoming


def remove_expense(expenses: List[Expense], expense_id: str) -> List[Expense]:
    return [expense for expense in expenses if expense.id != expense_id]


# --- backup, restore and export ------------------------------------------
#
# There are two different jobs here and conflating them loses data.
#
# A **backup** is the whole database, byte for byte, and is the only thing that
# restores everything: subscriptions, cards, every month marked paid, the login,
# the settings. It is not readable by anything but this application.
#
# An **export** is a CSV for a person to read, open in a spreadsheet, or keep
# somewhere legible in twenty years. It deliberately does not round-trip: it
# holds no identifiers and no payment history, so importing one back would
# silently lose things. Anyone relying on CSV as their safety net has the wrong
# idea, which is why the interface says so plainly.


BACKUP_SUFFIX = ".duekhata-backup.db"


def backup_file_name(today: Optional[date] = None) -> str:
    """A name that sorts chronologically and says what it is."""
    stamp = (today or date.today()).isoformat()
    return "DueKhata " + stamp + BACKUP_SUFFIX


def backup_database(data_file: Path, destination: Path) -> Path:
    """Copy the database to `destination`, safely, and return where it landed.

    Uses SQLite's own backup API rather than copying the file. A plain file copy
    of a database that is open can capture a partially written page, producing a
    backup that looks fine until the day it is needed. The backup API takes a
    consistent snapshot even while the application is using the database.
    """
    if not data_file.exists():
        raise FileNotFoundError("there is no database to back up yet")

    destination = Path(destination)
    if destination.is_dir():
        destination = destination / backup_file_name()
    destination.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(data_file)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return destination


def describe_backup(path: Path) -> dict:
    """What is in a backup file, without trusting its name.

    Called before restoring so the user is told what they are about to replace
    their data with, and so a file that is not a DueKhata backup is refused
    rather than copied over the top of everything.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError("that file does not exist")

    try:
        connection = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)
    except sqlite3.OperationalError as error:
        raise ValueError("that file cannot be opened as a database") from error

    try:
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "expenses" not in tables:
            raise ValueError("that database is not a DueKhata backup")

        def count(table: str) -> int:
            if table not in tables:
                return 0
            return connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

        return {
            "subscriptions": count("expenses"),
            "cards": count("cards"),
            "payments": count("expense_payments") + count("card_payments"),
            "size": path.stat().st_size,
        }
    except sqlite3.DatabaseError as error:
        raise ValueError("that file is not a readable database") from error
    finally:
        connection.close()


def restore_database(backup_path: Path, data_file: Path) -> Path:
    """Replace the live database with a backup, keeping the old one.

    The displaced database is written beside the live one with a `.replaced-`
    prefix and its path returned. Restoring is the one irreversible-looking
    action in the application, so it is made reversible: if someone restores the
    wrong file, what they had is still on disk.
    """
    backup_path = Path(backup_path)
    data_file = Path(data_file)

    # Refuses anything that is not a DueKhata database, before touching a thing.
    describe_backup(backup_path)

    displaced = None
    if data_file.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        displaced = data_file.with_name("replaced-" + stamp + "-" + data_file.name)
        source = sqlite3.connect(data_file)
        try:
            target = sqlite3.connect(displaced)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

    data_file.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(backup_path)
    try:
        target = sqlite3.connect(data_file)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    return displaced


SUBSCRIPTION_CSV_HEADER = (
    "Description",
    "Amount",
    "Repeats",
    "Per month",
    "Starts",
    "Ends",
    "Next due",
    "Category",
    "Charged to",
)


def export_subscriptions_csv(
    expenses: List[Expense],
    cards: List[Card],
    destination: Path,
    today: Optional[date] = None,
) -> Path:
    """Write the subscriptions as a spreadsheet a person can read.

    Column headings are the ones used in the application, not the database's
    field names, because the audience is whoever opens the file rather than
    whoever wrote the schema.
    """
    today = today or date.today()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # newline="" is required or the csv module writes blank lines on Windows.
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUBSCRIPTION_CSV_HEADER)
        for expense in sorted(expenses, key=lambda item: item.description.lower()):
            following = next_occurrence(expense, today)
            writer.writerow(
                [
                    expense.description,
                    "" if expense.amount is None else format(expense.amount, ".2f"),
                    CADENCE_LABELS.get(expense.cadence, expense.cadence or ""),
                    format(monthly_equivalent(expense), ".2f"),
                    expense.date or "",
                    expense.ends_on or "",
                    following.isoformat() if following else "",
                    expense.category,
                    payment_source_name(cards, expense.paid_with),
                ]
            )
    return destination


CARD_CSV_HEADER = ("Name", "Kind", "Due day", "Notes")


def export_cards_csv(cards: List[Card], destination: Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(CARD_CSV_HEADER)
        for card in sorted(cards, key=lambda item: (item.kind != KIND_CARD, item.name.lower())):
            writer.writerow(
                [
                    card.name,
                    KIND_LABELS.get(card.kind, card.kind),
                    "" if card.due_day is None else str(card.due_day),
                    card.notes,
                ]
            )
    return destination


PAYMENT_CSV_HEADER = ("Card", "Year", "Month", "Amount", "Recorded on")


def export_card_payments_csv(data_file: Path, destination: Path) -> Path:
    """Every card payment ever recorded, newest first."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if data_file.exists() and data_file.suffix.lower() != ".json":
        try:
            with _connect(data_file) as connection:
                rows = connection.execute(
                    """
                    SELECT c.name, p.paid_year, p.paid_month, p.amount, p.paid_on
                    FROM card_payments p
                    JOIN cards c ON c.id = p.card_id
                    ORDER BY p.paid_year DESC, p.paid_month DESC, c.name
                    """
                ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(PAYMENT_CSV_HEADER)
        for name, year, month, amount, paid_on in rows:
            writer.writerow([name, year, month, format(amount, ".2f"), paid_on])
    return destination
