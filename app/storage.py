from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class DbOrder:
    order_id: str
    user_id: int
    username: str | None
    country_code: str
    country_name: str
    vm_id: str
    vm_name: str
    vm_specs: str
    amount_rub: int
    payment_id: str
    created_at: datetime
    status: str
    provisioned_data: str | None
    platega_transaction_id: str | None = None


@dataclass(slots=True)
class BalanceTx:
    tx_id: int
    user_id: int
    username: str | None
    delta_rub: int
    balance_after_rub: int
    kind: str
    note: str | None
    created_at: datetime


@dataclass(slots=True)
class BalanceTopup:
    topup_id: str
    user_id: int
    username: str | None
    amount_rub: int
    created_at: datetime
    status: str
    platega_transaction_id: str | None
    confirmed_at: datetime | None


class Storage:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        if self._db_path.parent != Path("."):
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self._db_path)
        self._con.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self._con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance_rub INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orders (
                payment_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                country_code TEXT NOT NULL,
                country_name TEXT NOT NULL,
                vm_id TEXT NOT NULL,
                vm_name TEXT NOT NULL,
                vm_specs TEXT NOT NULL,
                amount_rub INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                provisioned_data TEXT,
                platega_transaction_id TEXT
            );

            CREATE TABLE IF NOT EXISTS group_order_messages (
                message_id INTEGER PRIMARY KEY,
                payment_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS balance_transactions (
                tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                delta_rub INTEGER NOT NULL,
                balance_after_rub INTEGER NOT NULL,
                kind TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS balance_topups (
                topup_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT,
                amount_rub INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                platega_transaction_id TEXT UNIQUE,
                confirmed_at TEXT
            );
            """
        )

        # Миграции для старых БД
        try:
            self._con.execute(
                "ALTER TABLE orders ADD COLUMN platega_transaction_id TEXT"
            )
            self._con.commit()
        except Exception:
            pass

        try:
            self._con.execute(
                "ALTER TABLE balance_topups ADD COLUMN confirmed_at TEXT"
            )
            self._con.commit()
        except Exception:
            pass

    def close(self) -> None:
        self._con.close()

    def ensure_user(self, user_id: int, username: str | None) -> None:
        self._con.execute(
            """
            INSERT INTO users(user_id, username, balance_rub)
            VALUES (?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
            """,
            (user_id, username),
        )
        self._con.commit()

    def get_user_balance(self, user_id: int) -> int:
        row = self._con.execute(
            "SELECT balance_rub FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["balance_rub"]) if row else 0

    def add_user_balance(
        self,
        user_id: int,
        username: str | None,
        amount_rub: int,
        kind: str = "topup",
        note: str | None = None,
    ) -> int:
        self.ensure_user(user_id, username)
        self._con.execute(
            "UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?",
            (amount_rub, user_id),
        )
        new_balance = self.get_user_balance(user_id)
        self._con.execute(
            """
            INSERT INTO balance_transactions(
                user_id, username, delta_rub, balance_after_rub, kind, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                amount_rub,
                new_balance,
                kind,
                note,
                datetime.utcnow().isoformat(),
            ),
        )
        self._con.commit()
        return new_balance

    def spend_user_balance(
        self,
        user_id: int,
        amount_rub: int,
        kind: str = "purchase",
        note: str | None = None,
    ) -> bool:
        self._con.execute("BEGIN IMMEDIATE")
        row = self._con.execute(
            "SELECT balance_rub FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        balance = int(row["balance_rub"]) if row else 0
        if balance < amount_rub:
            self._con.execute("ROLLBACK")
            return False

        self._con.execute(
            "UPDATE users SET balance_rub = balance_rub - ? WHERE user_id = ?",
            (amount_rub, user_id),
        )
        row_user = self._con.execute(
            "SELECT username, balance_rub FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row_user:
            self._con.execute(
                """
                INSERT INTO balance_transactions(
                    user_id, username, delta_rub, balance_after_rub, kind, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    row_user["username"],
                    -amount_rub,
                    int(row_user["balance_rub"]),
                    kind,
                    note,
                    datetime.utcnow().isoformat(),
                ),
            )
        self._con.commit()
        return True

    def create_order(self, order: DbOrder) -> None:
        self._con.execute(
            """
            INSERT INTO orders(
                payment_id, order_id, user_id, username, country_code, country_name,
                vm_id, vm_name, vm_specs, amount_rub, created_at, status,
                provisioned_data, platega_transaction_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.payment_id,
                order.order_id,
                order.user_id,
                order.username,
                order.country_code,
                order.country_name,
                order.vm_id,
                order.vm_name,
                order.vm_specs,
                order.amount_rub,
                order.created_at.isoformat(),
                order.status,
                order.provisioned_data,
                order.platega_transaction_id,
            ),
        )
        self._con.commit()

    def get_order(self, payment_id: str) -> DbOrder | None:
        row = self._con.execute(
            "SELECT * FROM orders WHERE payment_id = ?",
            (payment_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_order(row)

    def get_order_by_platega_id(self, platega_transaction_id: str) -> DbOrder | None:
        row = self._con.execute(
            "SELECT * FROM orders WHERE platega_transaction_id = ?",
            (platega_transaction_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_order(row)

    def set_platega_transaction_id(self, payment_id: str, platega_transaction_id: str) -> None:
        self._con.execute(
            "UPDATE orders SET platega_transaction_id = ? WHERE payment_id = ?",
            (platega_transaction_id, payment_id),
        )
        self._con.commit()

    def create_balance_topup(
        self,
        topup_id: str,
        user_id: int,
        username: str | None,
        amount_rub: int,
        platega_transaction_id: str,
        status: str = "waiting_payment",
    ) -> None:
        self.ensure_user(user_id, username)
        self._con.execute(
            """
            INSERT INTO balance_topups(
                topup_id, user_id, username, amount_rub,
                created_at, status, platega_transaction_id, confirmed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                topup_id,
                user_id,
                username,
                amount_rub,
                datetime.utcnow().isoformat(),
                status,
                platega_transaction_id,
            ),
        )
        self._con.commit()

    def get_balance_topup(self, topup_id: str) -> BalanceTopup | None:
        row = self._con.execute(
            "SELECT * FROM balance_topups WHERE topup_id = ?",
            (topup_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_balance_topup(row)

    def get_balance_topup_by_platega_id(self, platega_transaction_id: str) -> BalanceTopup | None:
        row = self._con.execute(
            "SELECT * FROM balance_topups WHERE platega_transaction_id = ?",
            (platega_transaction_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_balance_topup(row)

    def set_balance_topup_platega_transaction_id(self, topup_id: str, platega_transaction_id: str) -> None:
        self._con.execute(
            "UPDATE balance_topups SET platega_transaction_id = ? WHERE topup_id = ?",
            (platega_transaction_id, topup_id),
        )
        self._con.commit()

    def update_balance_topup_status(self, topup_id: str, status: str) -> None:
        if status not in ("waiting_payment", "confirmed", "canceled"):
            raise ValueError("invalid topup status")
        self._con.execute(
            "UPDATE balance_topups SET status = ? WHERE topup_id = ?",
            (status, topup_id),
        )
        self._con.commit()

    def cancel_balance_topup(self, topup_id: str) -> bool:
        self._con.execute("BEGIN IMMEDIATE")
        row = self._con.execute(
            "SELECT status FROM balance_topups WHERE topup_id = ?",
            (topup_id,),
        ).fetchone()
        if row is None:
            self._con.execute("ROLLBACK")
            return False
        if str(row["status"]) != "waiting_payment":
            self._con.execute("ROLLBACK")
            return False
        self._con.execute(
            """
            UPDATE balance_topups
            SET status = 'canceled'
            WHERE topup_id = ?
            """,
            (topup_id,),
        )
        self._con.commit()
        return True

    def credit_balance_topup(self, topup_id: str) -> int | None:
        """
        Атомарно начисляет баланс по пополнению.
        Возвращает новый баланс или None, если пополнение уже обработано / не найдено.
        """
        self._con.execute("BEGIN IMMEDIATE")
        try:
            row = self._con.execute(
                "SELECT * FROM balance_topups WHERE topup_id = ?",
                (topup_id,),
            ).fetchone()
            if row is None or str(row["status"]) != "waiting_payment":
                self._con.execute("ROLLBACK")
                return None

            user_id = int(row["user_id"])
            username = row["username"]
            amount_rub = int(row["amount_rub"])

            self._con.execute(
                """
                INSERT INTO users(user_id, username, balance_rub)
                VALUES (?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
                """,
                (user_id, username),
            )
            self._con.execute(
                "UPDATE users SET balance_rub = balance_rub + ? WHERE user_id = ?",
                (amount_rub, user_id),
            )
            user_row = self._con.execute(
                "SELECT balance_rub FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            new_balance = int(user_row["balance_rub"]) if user_row else amount_rub

            self._con.execute(
                """
                INSERT INTO balance_transactions(
                    user_id, username, delta_rub, balance_after_rub, kind, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    amount_rub,
                    new_balance,
                    "topup",
                    f"platega_topup:{topup_id}",
                    datetime.utcnow().isoformat(),
                ),
            )
            self._con.execute(
                """
                UPDATE balance_topups
                SET status = 'confirmed', confirmed_at = ?
                WHERE topup_id = ?
                """,
                (datetime.utcnow().isoformat(), topup_id),
            )
            self._con.commit()
            return new_balance
        except Exception:
            self._con.execute("ROLLBACK")
            raise

    def list_user_orders(self, user_id: int, limit: int = 10) -> list[DbOrder]:
        rows = self._con.execute(
            """
            SELECT * FROM orders
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def update_order_status(self, payment_id: str, status: str) -> None:
        self._con.execute(
            "UPDATE orders SET status = ? WHERE payment_id = ?",
            (status, payment_id),
        )
        self._con.commit()

    def admin_set_order_status(self, payment_id: str, status: str) -> None:
        if status not in (
            "waiting_payment",
            "paid_waiting_provision",
            "provisioned",
        ):
            raise ValueError("invalid status")
        if status == "provisioned":
            row = self._con.execute(
                "SELECT provisioned_data FROM orders WHERE payment_id = ?",
                (payment_id,),
            ).fetchone()
            prev = row["provisioned_data"] if row else None
            data = prev if prev else (
                "— Отмечено в админ-панели. Реквизиты доступа будут отправлены отдельно."
            )
            self._con.execute(
                """
                UPDATE orders SET status = 'provisioned', provisioned_data = ?
                WHERE payment_id = ?
                """,
                (data, payment_id),
            )
        else:
            self._con.execute(
                """
                UPDATE orders SET status = ?, provisioned_data = NULL
                WHERE payment_id = ?
                """,
                (status, payment_id),
            )
        self._con.commit()

    def set_order_provisioned(self, payment_id: str, provisioned_data: str) -> None:
        self._con.execute(
            """
            UPDATE orders
            SET status = 'provisioned', provisioned_data = ?
            WHERE payment_id = ?
            """,
            (provisioned_data, payment_id),
        )
        self._con.commit()

    def link_group_message(self, message_id: int, payment_id: str) -> None:
        self._con.execute(
            """
            INSERT INTO group_order_messages(message_id, payment_id)
            VALUES (?, ?)
            ON CONFLICT(message_id) DO UPDATE SET payment_id=excluded.payment_id
            """,
            (message_id, payment_id),
        )
        self._con.commit()

    def get_payment_id_by_group_message(self, message_id: int) -> str | None:
        row = self._con.execute(
            "SELECT payment_id FROM group_order_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return str(row["payment_id"]) if row else None

    def count_orders(self) -> int:
        row = self._con.execute("SELECT COUNT(*) AS c FROM orders").fetchone()
        return int(row["c"]) if row else 0

    def count_orders_by_status(self) -> dict[str, int]:
        rows = self._con.execute(
            "SELECT status, COUNT(*) AS c FROM orders GROUP BY status"
        ).fetchall()
        return {str(r["status"]): int(r["c"]) for r in rows}

    def revenue_paid_rub(self) -> int:
        row = self._con.execute(
            """
            SELECT COALESCE(SUM(amount_rub), 0) AS s FROM orders
            WHERE status IN ('paid_waiting_provision', 'provisioned')
            """
        ).fetchone()
        return int(row["s"]) if row else 0

    def list_orders_admin(self, limit: int, offset: int) -> list[DbOrder]:
        rows = self._con.execute(
            """
            SELECT * FROM orders
            ORDER BY datetime(created_at) DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def stats_sales_by_country(self) -> list[tuple[str, str, int, int]]:
        rows = self._con.execute(
            """
            SELECT country_code, country_name,
                   COUNT(*) AS cnt,
                   COALESCE(SUM(amount_rub), 0) AS rev
            FROM orders
            WHERE status IN ('paid_waiting_provision', 'provisioned')
            GROUP BY country_code, country_name
            ORDER BY rev DESC, cnt DESC
            """
        ).fetchall()
        return [
            (str(r["country_code"]), str(r["country_name"]), int(r["cnt"]), int(r["rev"]))
            for r in rows
        ]

    def count_users(self) -> int:
        row = self._con.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"]) if row else 0

    def list_users_admin(
        self, limit: int, offset: int
    ) -> list[tuple[int, str | None, int, int]]:
        rows = self._con.execute(
            """
            SELECT u.user_id, u.username, u.balance_rub,
                   (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.user_id) AS oc
            FROM users u
            ORDER BY u.user_id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [
            (int(r["user_id"]), r["username"], int(r["balance_rub"]), int(r["oc"]))
            for r in rows
        ]

    def list_user_balance_transactions(self, user_id: int, limit: int = 8) -> list[BalanceTx]:
        rows = self._con.execute(
            """
            SELECT * FROM balance_transactions
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC, tx_id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [self._row_to_balance_tx(row) for row in rows]

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> DbOrder:
        cols = row.keys()
        platega_tid = row["platega_transaction_id"] if "platega_transaction_id" in cols else None
        return DbOrder(
            order_id=str(row["order_id"]),
            user_id=int(row["user_id"]),
            username=row["username"],
            country_code=str(row["country_code"]),
            country_name=str(row["country_name"]),
            vm_id=str(row["vm_id"]),
            vm_name=str(row["vm_name"]),
            vm_specs=str(row["vm_specs"]),
            amount_rub=int(row["amount_rub"]),
            payment_id=str(row["payment_id"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            status=str(row["status"]),
            provisioned_data=row["provisioned_data"],
            platega_transaction_id=platega_tid,
        )

    @staticmethod
    def _row_to_balance_tx(row: sqlite3.Row) -> BalanceTx:
        return BalanceTx(
            tx_id=int(row["tx_id"]),
            user_id=int(row["user_id"]),
            username=row["username"],
            delta_rub=int(row["delta_rub"]),
            balance_after_rub=int(row["balance_after_rub"]),
            kind=str(row["kind"]),
            note=row["note"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _row_to_balance_topup(row: sqlite3.Row) -> BalanceTopup:
        confirmed_at_raw = row["confirmed_at"] if "confirmed_at" in row.keys() else None
        confirmed_at = (
            datetime.fromisoformat(str(confirmed_at_raw))
            if confirmed_at_raw
            else None
        )
        return BalanceTopup(
            topup_id=str(row["topup_id"]),
            user_id=int(row["user_id"]),
            username=row["username"],
            amount_rub=int(row["amount_rub"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            status=str(row["status"]),
            platega_transaction_id=row["platega_transaction_id"],
            confirmed_at=confirmed_at,
        )