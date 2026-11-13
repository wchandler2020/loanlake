"""Names and paths for one environment. Every notebook builds a Layout from its catalog."""
from __future__ import annotations

from dataclasses import dataclass

SCHEMAS = ("landing", "bronze", "silver", "gold")


@dataclass(frozen=True)
class Layout:
    catalog: str

    @property
    def landing_raw(self) -> str:
        """Where the upstream system drops files (a Unity Catalog volume)."""
        return f"/Volumes/{self.catalog}/landing/raw"

    @property
    def checkpoints(self) -> str:
        """Where streaming checkpoints and Auto Loader schemas live (a separate volume)."""
        return f"/Volumes/{self.catalog}/landing/checkpoints"

    def table(self, schema: str, name: str) -> str:
        return f"{self.catalog}.{schema}.{name}"


def get_param(dbutils, name: str, default: str) -> str:
    """Read a job parameter; fall back to default when the notebook is run by hand."""
    try:
        value = dbutils.widgets.get(name)
    except Exception:  # no such parameter: running interactively
        return default
    return value or default