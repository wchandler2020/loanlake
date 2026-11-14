"""Fake upstream loan-servicing system.

Each call to generate_batch() drops one business month of files into the
landing zone, the way a vendor lands files for you every night.
The data is deliberately messy so the pipeline has real problems to solve:
  - duplicate payment records           -> dedupe in Silver
  - null / negative amounts, bad dates  -> quarantine in Silver
  - payments for a loan that isn't real -> referential-integrity check in Silver
  - borrowers changing state or tier    -> SCD Type 2 in Silver
  - a new column appearing in month 5   -> schema evolution in Bronze
Same batch number in = same files out (seeded), so every run is reproducible.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date
from pathlib import Path

START_MONTH = date(2026, 1, 1)   # business month of batch 0
N_BORROWERS = 500                # borrowers that exist on day one
NEW_PER_MONTH = 20               # new borrowers (and loans) each month after that
CHANGE_RATE = 0.03               # share of borrowers whose state or tier changes each month
SCHEMA_DRIFT_BATCH = 4           # from this batch on, payments carry processor_ref
ORPHAN_LOAN_ID = "L999999"       # a loan id that never exists
BAD_DATE = "13/45/2026"          # a payment_date that can't be parsed

STATES = ["IL", "WI", "IN", "MI", "OH", "MN", "IA", "MO"]
TIERS = ["A", "B", "C", "D"]
PAY_PROB = {"A": 0.98, "B": 0.95, "C": 0.88, "D": 0.75}   # chance a borrower pays this month
CHANNELS = ["ACH", "CHECK", "ONLINE", "PHONE"]
FIRST = ["James", "Maria", "Robert", "Linda", "Michael", "Patricia", "David", "Jennifer", "William", "Elizabeth"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Martinez", "Wilson"]


def _rng(*parts: object) -> random.Random:
    """A random generator seeded from the given parts, so output is repeatable."""
    return random.Random("|".join(map(str, parts)))


def business_month(batch: int) -> date:
    """Batch 0 -> 2026-01-01, batch 1 -> 2026-02-01, and so on."""
    years, month_index = divmod(START_MONTH.month - 1 + batch, 12)
    return date(START_MONTH.year + years, month_index + 1, 1)


def _new_borrower_ids(batch: int) -> list[int]:
    """Borrower ids first seen in this batch."""
    if batch == 0:
        return list(range(1, N_BORROWERS + 1))
    first = N_BORROWERS + (batch - 1) * NEW_PER_MONTH + 1
    return list(range(first, first + NEW_PER_MONTH))


def _ids_through(batch: int) -> list[int]:
    """Every borrower id that exists as of this batch."""
    return list(range(1, N_BORROWERS + batch * NEW_PER_MONTH + 1))


def _base_borrower(borrower_id: int) -> dict:
    r = _rng("borrower", borrower_id)
    return {
        "borrower_id": borrower_id,
        "first_name": r.choice(FIRST),
        "last_name": r.choice(LAST),
        "state": r.choice(STATES),
        "credit_tier": r.choice(TIERS),
    }


def _origination(borrower_id: int) -> date:
    """Day-one loans were originated mid-2025; later ones in the month they appear."""
    if borrower_id <= N_BORROWERS:
        return date(2025, 6, 1)
    return business_month((borrower_id - N_BORROWERS - 1) // NEW_PER_MONTH + 1)


def _loan(borrower_id: int) -> dict:
    r = _rng("loan", borrower_id)
    return {
        "loan_id": f"L{borrower_id:06d}",
        "borrower_id": borrower_id,
        "principal": r.randrange(100_000, 600_001, 1_000),
        "annual_rate": round(r.uniform(0.055, 0.075), 4),
        "term_months": 360,
        "origination_date": _origination(borrower_id).isoformat(),
    }


def monthly_installment(principal: float, annual_rate: float, term_months: int) -> float:
    """Standard amortizing payment: P * r / (1 - (1 + r) ** -n), r = monthly rate."""
    r = annual_rate / 12
    return round(principal * r / (1 - (1 + r) ** -term_months), 2)


def _borrower_rows(batch: int, as_of: date) -> list[dict]:
    """New borrowers, plus existing borrowers whose state or tier changed (a CDC feed)."""
    rows = [_base_borrower(i) for i in _new_borrower_ids(batch)]
    if batch > 0:
        r = _rng("changes", batch)
        existing = _ids_through(batch - 1)
        for borrower_id in r.sample(existing, int(len(existing) * CHANGE_RATE)):
            row = _base_borrower(borrower_id)
            if r.random() < 0.5:
                row["state"] = r.choice(STATES)
            else:
                row["credit_tier"] = r.choice(TIERS)
            rows.append(row)
    stamp = f"{as_of.isoformat()}T06:00:00"
    return [{**row, "updated_at": stamp} for row in rows]


def _payment_rows(batch: int, as_of: date) -> list[dict]:
    """One payment per loan that pays this month. New loans start paying the month after."""
    r = _rng("payments", batch)
    rows = []
    for borrower_id in _ids_through(max(batch - 1, 0)):
        tier = _base_borrower(borrower_id)["credit_tier"]
        if r.random() > PAY_PROB[tier]:
            continue  # missed payment -> drives delinquency in Gold
        loan = _loan(borrower_id)
        row = {
            "payment_id": f"P{as_of:%Y%m}-{loan['loan_id']}",
            "loan_id": loan["loan_id"],
            "payment_date": as_of.replace(day=r.randint(1, 28)).isoformat(),
            "amount": monthly_installment(loan["principal"], loan["annual_rate"], loan["term_months"]),
            "channel": r.choice(CHANNELS),
        }
        if batch >= SCHEMA_DRIFT_BATCH:
            row["processor_ref"] = f"TX{r.randrange(10**9):09d}"
        rows.append(row)
    return _make_messy(rows, r)


def _make_messy(rows: list[dict], r: random.Random) -> list[dict]:
    """Inject a small, fixed number of each kind of bad record."""
    k = max(1, len(rows) // 200)  # about 0.5% of rows per problem type
    picks = r.sample(range(len(rows)), k * 4)
    for i in picks[0:k]:
        rows[i]["amount"] = None
    for i in picks[k:2 * k]:
        rows[i]["amount"] = -rows[i]["amount"]
    for i in picks[2 * k:3 * k]:
        rows[i]["payment_date"] = BAD_DATE
    for i in picks[3 * k:4 * k]:
        rows[i]["loan_id"] = ORPHAN_LOAN_ID
    duplicates = [dict(rows[i]) for i in r.sample(range(len(rows)), k)]
    return rows + duplicates


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def next_batch(root: str) -> int:
    """Months already landed = the next batch number."""
    payments = Path(root) / "payments"
    if not payments.exists():
        return 0
    return sum(1 for p in payments.iterdir() if p.is_dir())


def generate_batch(root: str, batch: int) -> dict:
    """Land one business month of borrower, loan and payment files under root."""
    as_of = business_month(batch)
    folder = as_of.isoformat()
    base = Path(root)
    borrowers = _borrower_rows(batch, as_of)
    loans = [_loan(i) for i in _new_borrower_ids(batch)]
    payments = _payment_rows(batch, as_of)
    _write_csv(base / "borrowers" / folder / "borrowers.csv", borrowers)
    _write_csv(base / "loans" / folder / "loans.csv", loans)
    _write_jsonl(base / "payments" / folder / "payments.json", payments)  # last: next_batch counts these
    return {
        "batch": batch,
        "business_month": folder,
        "borrowers": len(borrowers),
        "loans": len(loans),
        "payments": len(payments),
    }