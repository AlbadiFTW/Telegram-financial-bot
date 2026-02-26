"""
finance.py — Pure algorithms (no DB, no Telegram).
  • compute_balances  — net per-person balance from raw debt rows
  • minimal_transfers — greedy O(n log n) debt-settlement optimizer
  • parse_csv_transactions — flexible CSV import
  • categorize_description — keyword-based auto-category
"""

from __future__ import annotations

import csv
import io
import re
from typing import Optional, List, Dict, Tuple, Set


# ══════════════════════════════════════════════════════════════════════════════
# DEBT SETTLEMENT MATH
# ══════════════════════════════════════════════════════════════════════════════

def compute_balances(debt_rows: List[Dict]) -> Dict[str, float]:
    """
    Given raw debt rows [{creditor, debtor, amount}], compute net balance
    per person from "me"'s perspective.

    Positive  → person owes ME money
    Negative  → I owe that person money
    """
    net: dict[str, float] = {}

    for row in debt_rows:
        creditor = row["creditor"].lower()
        debtor   = row["debtor"].lower()
        amount   = float(row["amount"])

        if creditor == "me":
            # debtor owes me
            net[debtor] = net.get(debtor, 0) + amount
        elif debtor == "me":
            # I owe creditor
            net[creditor] = net.get(creditor, 0) - amount
        else:
            # Third-party debt (logged for completeness)
            net[debtor]   = net.get(debtor,   0) - amount
            net[creditor] = net.get(creditor, 0) + amount

    # Remove zero-balance entries
    return {k: round(v, 2) for k, v in net.items() if abs(v) >= 0.01}


def minimal_transfers(balances: Dict[str, float]) -> List[Tuple[str, str, float]]:
    """
    Compute the minimum number of transfers to settle all debts.

    Algorithm:
      1. Separate into creditors (net positive) and debtors (net negative)
      2. Greedily match largest creditor with largest debtor
      3. Each iteration eliminates at least one person from the list
      → At most N-1 transfers for N people

    Returns: [(payer, receiver, amount), ...]
    """
    creditors: List[list] = sorted(
        [[v, k] for k, v in balances.items() if v > 0], reverse=True
    )
    debtors: List[list] = sorted(
        [[abs(v), k] for k, v in balances.items() if v < 0], reverse=True
    )

    transfers: List[Tuple[str, str, float]] = []
    i, j = 0, 0

    while i < len(creditors) and j < len(debtors):
        credit, creditor = creditors[i]
        debt,   debtor   = debtors[j]

        amount = round(min(credit, debt), 2)
        transfers.append((debtor, creditor, amount))

        creditors[i][0] = round(credit - amount, 2)
        debtors[j][0]   = round(debt   - amount, 2)

        if creditors[i][0] < 0.01:
            i += 1
        if debtors[j][0] < 0.01:
            j += 1

    return transfers


# ══════════════════════════════════════════════════════════════════════════════
# CSV IMPORT
# ══════════════════════════════════════════════════════════════════════════════

# Common column name aliases used by different banks
_DATE_COLS   = {"date", "transaction date", "trans date", "value date", "posted date", "تاريخ"}
_DESC_COLS   = {"description", "narrative", "details", "memo", "particulars", "transaction", "بيان"}
_AMOUNT_COLS = {"amount", "debit/credit", "value", "sum", "المبلغ"}
_DEBIT_COLS  = {"debit", "withdrawal", "سحب"}
_CREDIT_COLS = {"credit", "deposit", "إيداع"}


def _find_col(headers: List[str], candidates: Set[str]) -> Optional[int]:
    for i, h in enumerate(headers):
        if h.strip().lower() in candidates:
            return i
    return None


def _parse_amount(value: str) -> Optional[float]:
    """Parse amount string, stripping currency symbols and commas."""
    cleaned = re.sub(r"[^\d.\-+]", "", value.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_csv_transactions(csv_text: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse a CSV bank export into a list of transaction dicts.

    Supports formats:
      date, description, amount          (negative = debit)
      date, description, debit, credit   (separate columns)

    Returns (transactions, errors)
    Each transaction: {date, description, amount}  (negative = spend)
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows   = list(reader)

    if not rows:
        return [], ["Empty file"]

    # Find header row (first row with recognizable columns)
    header_idx = None
    headers    = []
    for idx, row in enumerate(rows):
        normalized = [c.strip().lower() for c in row]
        if any(c in _DATE_COLS | _DESC_COLS | _AMOUNT_COLS for c in normalized):
            header_idx = idx
            headers    = normalized
            break

    if header_idx is None:
        return [], ["No recognizable header row found"]

    date_col   = _find_col(headers, _DATE_COLS)
    desc_col   = _find_col(headers, _DESC_COLS)
    amt_col    = _find_col(headers, _AMOUNT_COLS)
    debit_col  = _find_col(headers, _DEBIT_COLS)
    credit_col = _find_col(headers, _CREDIT_COLS)

    transactions: List[Dict] = []
    errors: List[str]        = []

    for row in rows[header_idx + 1:]:
        if not any(cell.strip() for cell in row):
            continue  # skip blank lines

        # Get description
        description = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else "transaction"

        # Get date
        date_str = row[date_col].strip() if date_col is not None and date_col < len(row) else None

        # Get amount
        amount = None
        if amt_col is not None and amt_col < len(row):
            amount = _parse_amount(row[amt_col])
        elif debit_col is not None and credit_col is not None:
            debit  = _parse_amount(row[debit_col])  if debit_col  < len(row) else None
            credit = _parse_amount(row[credit_col]) if credit_col < len(row) else None
            if debit  and abs(debit)  > 0.001: amount = -abs(debit)
            if credit and abs(credit) > 0.001: amount =  abs(credit)

        if amount is None:
            errors.append(f"Could not parse amount in row: {row}")
            continue

        transactions.append({
            "date":        date_str,
            "description": description,
            "amount":      round(amount, 2),   # negative = spend
        })

    return transactions, errors


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-CATEGORIZATION
# ══════════════════════════════════════════════════════════════════════════════

_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "food": [
        "restaurant", "cafe", "coffee", "starbucks", "mcdonald", "kfc", "burger",
        "pizza", "subway", "shawarma", "lunch", "dinner", "breakfast", "food",
        "grocery", "supermarket", "carrefour", "lulu", "spinneys", "waitrose",
        "bakery", "sushi", "noodle", "فطور", "غداء", "عشاء", "مطعم"
    ],
    "transport": [
        "uber", "careem", "taxi", "fuel", "petrol", "gas station", "adnoc", "enoc",
        "parking", "metro", "bus", "transport", "toll", "salik", "نقل", "بنزين"
    ],
    "shopping": [
        "amazon", "noon", "ikea", "zara", "h&m", "lulu", "mall", "shop", "store",
        "electronics", "apple", "samsung", "clothes", "fashion", "تسوق"
    ],
    "bills": [
        "etisalat", "du", "addc", "dewa", "utility", "electricity", "water",
        "internet", "phone", "netflix", "spotify", "subscription", "rent",
        "insurance", "فاتورة", "كهرباء", "ماء"
    ],
    "entertainment": [
        "cinema", "movie", "theatre", "concert", "event", "ticket", "game",
        "bowling", "gym", "theme park", "yas", "ferrari", "global village", "ترفيه"
    ],
    "health": [
        "pharmacy", "hospital", "clinic", "doctor", "medical", "medicine",
        "dentist", "optical", "health", "صيدلية", "مستشفى", "طبيب"
    ],
    "travel": [
        "airline", "flight", "hotel", "airbnb", "booking", "expedia",
        "etihad", "emirates", "flydubai", "airport", "visa", "سفر"
    ],
    "income": [
        "salary", "payroll", "transfer in", "deposit", "refund", "cashback", "راتب"
    ],
}


def categorize_description(description: str) -> str:
    """Keyword-match a transaction description to a category."""
    desc_lower = description.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return category
    return "other"
