"""Quais dias arquivar e em que lotes (funções puras, sem nuvem)."""

from datetime import date, datetime


def partition_dates(partition_ids: list[str]) -> list[date]:
    """IDs de partição diária do BigQuery ('20251021') → datas. Ignora __NULL__ e afins."""
    dates = []
    for pid in partition_ids:
        if pid.isdigit() and len(pid) == 8:
            dates.append(datetime.strptime(pid, "%Y%m%d").date())
    return sorted(dates)


def dates_to_archive(partition_ids: list[str], cutoff: date) -> list[date]:
    return [d for d in partition_dates(partition_ids) if d < cutoff]


def chunks(dates: list[date], size: int) -> list[list[date]]:
    """Lotes de até `size` dias, na ordem."""
    return [dates[i : i + size] for i in range(0, len(dates), size)]
