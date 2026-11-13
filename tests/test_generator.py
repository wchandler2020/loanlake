import json
from pathlib import Path

from loanlake import generator
from loanlake.config import get_param


def _read_all(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()}


def _payments(root: Path, batch: int) -> list[dict]:
    month = generator.business_month(batch).isoformat()
    lines = (root / "payments" / month / "payments.json").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_same_batch_gives_same_files(tmp_path):
    generator.generate_batch(str(tmp_path / "a"), 0)
    generator.generate_batch(str(tmp_path / "b"), 0)
    assert _read_all(tmp_path / "a") == _read_all(tmp_path / "b")


def test_next_batch_advances(tmp_path):
    assert generator.next_batch(str(tmp_path)) == 0
    generator.generate_batch(str(tmp_path), 0)
    assert generator.next_batch(str(tmp_path)) == 1


def test_payments_include_every_kind_of_problem(tmp_path):
    generator.generate_batch(str(tmp_path), 0)
    rows = _payments(tmp_path, 0)
    ids = [r["payment_id"] for r in rows]
    assert len(ids) > len(set(ids))                                   # duplicates
    assert any(r["amount"] is None for r in rows)                     # null amount
    assert any(r["amount"] is not None and r["amount"] < 0 for r in rows)  # negative amount
    assert any(r["payment_date"] == generator.BAD_DATE for r in rows)
    assert any(r["loan_id"] == generator.ORPHAN_LOAN_ID for r in rows)


def test_processor_ref_appears_at_drift_batch(tmp_path):
    before, after = generator.SCHEMA_DRIFT_BATCH - 1, generator.SCHEMA_DRIFT_BATCH
    generator.generate_batch(str(tmp_path), before)
    generator.generate_batch(str(tmp_path), after)
    assert all("processor_ref" not in r for r in _payments(tmp_path, before))
    assert all("processor_ref" in r for r in _payments(tmp_path, after))


class _FakeWidgets:
    def __init__(self, values):
        self.values = values

    def get(self, name):
        if name not in self.values:
            raise ValueError(f"No widget named {name}")
        return self.values[name]


class _FakeDbutils:
    def __init__(self, values):
        self.widgets = _FakeWidgets(values)


def test_get_param_uses_job_value_then_default():
    assert get_param(_FakeDbutils({"catalog": "loanlake_prod"}), "catalog", "loanlake_dev") == "loanlake_prod"
    assert get_param(_FakeDbutils({}), "catalog", "loanlake_dev") == "loanlake_dev"
    assert get_param(_FakeDbutils({"catalog": ""}), "catalog", "loanlake_dev") == "loanlake_dev"