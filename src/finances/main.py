import argparse
import csv
import datetime as dt
import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from tkinter import StringVar, Tk, filedialog, ttk
from typing import TypedDict

import sqlalchemy as sa
from ofxtools.Parser import OFXTree
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import Account, SessionLocal, Transaction

logging.basicConfig(
    format="%(levelname)s [%(asctime)s] - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Import transactions from OFX file into the database."""
    # Try to get file path from CLI, fall back to interactive dialog
    file_path = get_file_path_from_cli()
    if not file_path:
        file_path = get_file_path_interactive()

    if not file_path:
        logger.info("No file selected. Exiting.")
        return

    with SessionLocal() as session:
        account_id = select_account_interactive(session)
        if account_id is None:
            logger.info("No account selected. Exiting.")
            return

    logger.info("Reading OFX file: %s", file_path)
    ofx_transactions = read_ofx_file(file_path)
    if not ofx_transactions:
        logger.error("Failed to parse OFX file")
        return

    logger.info("Found %d transactions in OFX file", len(ofx_transactions))

    with SessionLocal() as session:
        new_transactions = insert_new_transactions(
            session, ofx_transactions, account_id=account_id
        )

    logger.info("Imported %d new transaction(s)", len(new_transactions))
    log_skipped_transactions(ofx_transactions, new_transactions)

    if not new_transactions:
        logger.info("No new transactions to export")
        return

    # Export the CSV for Simplifi
    export_to_csv(new_transactions)


def get_file_path_from_cli() -> Path | None:
    """Get OFX file path from command line arguments."""
    parser = argparse.ArgumentParser(
        description="Import transactions from an OFX file into the database."
    )
    parser.add_argument(
        "ofx_file",
        nargs="?",
        type=Path,
        help="Path to the OFX file to import",
    )
    args = parser.parse_args()

    if args.ofx_file:
        if args.ofx_file.exists() and args.ofx_file.suffix.lower() == ".ofx":
            return args.ofx_file
        logger.warning("File not found or not an OFX file: %s", args.ofx_file)
        return None
    return None


def get_file_path_interactive() -> Path | None:
    """Prompt user to select an OFX file interactively."""
    root = Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select OFX file",
        filetypes=[("OFX files", "*.ofx"), ("All files", "*.*")],
    )
    root.destroy()

    if file_path:
        return Path(file_path)

    return None


def select_account_interactive(session: Session) -> int | None:
    """Show a GUI dropdown to select an account."""
    accounts = (
        session.execute(sa.select(Account).order_by(Account.name)).scalars().all()
    )
    if not accounts:
        logger.warning("No accounts available in the database.")
        return None

    root = Tk()
    root.title("Select Account")
    root.resizable(False, False)
    root.lift()
    root.attributes("-topmost", True)
    root.after_idle(lambda: root.attributes("-topmost", False))

    account_names = [account.name for account in accounts]
    selected_name = StringVar(value=account_names[0])

    ttk.Label(root, text="Choose an account:").grid(
        column=0, row=0, padx=12, pady=(12, 6), sticky="w"
    )
    account_combo = ttk.Combobox(
        root,
        textvariable=selected_name,
        values=account_names,
        state="readonly",
        width=40,
    )
    account_combo.grid(column=0, row=1, padx=12, pady=(0, 12))
    account_combo.current(0)

    selected_account_id = {"value": None}

    def on_ok() -> None:
        selected = selected_name.get()
        for account in accounts:
            if account.name == selected:
                selected_account_id["value"] = account.id
                break
        root.destroy()

    def on_cancel() -> None:
        root.destroy()

    button_frame = ttk.Frame(root)
    button_frame.grid(column=0, row=2, padx=12, pady=(0, 12), sticky="e")
    ttk.Button(button_frame, text="OK", command=on_ok).grid(
        column=0, row=0, padx=(0, 8)
    )
    ttk.Button(button_frame, text="Cancel", command=on_cancel).grid(column=1, row=0)

    root.mainloop()
    return selected_account_id["value"]


class TransactionDict(TypedDict):
    date: date
    payee: str
    amount: float
    category: str
    tags: str
    notes: str
    check_no: str
    transaction_id: str


def read_ofx_file(file_path: Path) -> list[TransactionDict] | None:
    """Read transactions from an OFX file using ofxtools."""
    try:
        parser = OFXTree()
        parser.parse(str(file_path))
        ofx = parser.convert()

        if not ofx.statements:
            return None

        transactions = []
        for stmt in ofx.statements:
            transactions.extend(
                [
                    {
                        "date": trans.dtposted.date(),
                        "payee": trans.name or "",
                        "amount": float(trans.trnamt),
                        "category": "",
                        "tags": "",
                        "notes": "",
                        "check_no": "",
                        "transaction_id": trans.fitid,
                    }
                    for trans in stmt.transactions
                ]
            )
    except Exception:
        return None
    else:
        return transactions


def insert_new_transactions(
    session: Session,
    transactions: list[TransactionDict],
    account_id: int,
) -> Sequence[Transaction]:
    """Bulk insert transactions into the database, skipping duplicates."""

    stmt = (
        sqlite_insert(Transaction)
        .values(
            [
                {
                    "date": trans["date"],
                    "payee": trans["payee"],
                    "amount": trans["amount"],
                    "category": trans["category"],
                    "tags": trans["tags"],
                    "notes": trans["notes"],
                    "check_no": trans["check_no"],
                    "transaction_id": trans["transaction_id"],
                    "account_id": account_id,
                }
                for trans in transactions
            ]
        )
        .on_conflict_do_nothing(index_elements=["transaction_id"])
        .returning(Transaction)
    )
    result = session.execute(stmt).scalars().all()
    session.commit()

    return result


def log_skipped_transactions(
    all_transactions: list[TransactionDict],
    inserted_transactions: Sequence[Transaction],
) -> None:
    """Log transactions from the file that were skipped during insert."""
    inserted_ids = {transaction.transaction_id for transaction in inserted_transactions}
    for transaction in all_transactions:
        if transaction["transaction_id"] not in inserted_ids:
            logger.debug("Skipped transaction: %s", transaction["transaction_id"])


def export_to_csv(transactions: Sequence[Transaction]) -> None:
    """Export transactions to a CSV file."""
    fieldnames = ["Date", "Payee", "Amount", "Category", "Tags", "Notes", "Check_No"]

    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    dated_filename = (
        downloads_dir / f"imported_{dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')}.csv"
    )

    with open(dated_filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for transaction in transactions:
            writer.writerow(
                {
                    "Date": transaction.date.isoformat(),
                    "Payee": transaction.payee or "",
                    "Amount": transaction.amount,
                    "Category": transaction.category or "",
                    "Tags": transaction.tags or "",
                    "Notes": transaction.notes or "",
                    "Check_No": transaction.check_no or "",
                }
            )

    logger.info("Exported %d transactions to %s", len(transactions), dated_filename)


if __name__ == "__main__":
    main()
