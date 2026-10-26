"""Результаты в CSV с продолжением с места остановки + списки находок."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from . import statuses as st
from .pipeline import Result

FIELDS = ["username", "length", "status", "source", "detail", "checked_at"]


class ResultStore:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / "results.csv"
        self.rows: dict[str, dict] = {}
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        if not is_new:
            with open(self.path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    self.rows[row["username"]] = row
        # utf-8-sig, чтобы Excel правильно показал русский текст
        self._file = open(self.path, "a", newline="", encoding="utf-8-sig" if is_new else "utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDS)
        if is_new:
            self._writer.writeheader()

    def is_done(self, username: str) -> bool:
        row = self.rows.get(username)
        return row is not None and row["status"] != st.ERROR

    def add(self, result: Result) -> None:
        row = {
            "username": result.username,
            "length": len(result.username),
            "status": result.status,
            "source": result.source,
            "detail": result.detail,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._writer.writerow(row)
        self._file.flush()
        self.rows[result.username] = row

    def write_findings(self) -> dict[str, Path]:
        """free.txt, likely_free.txt, fragment.txt — короткие и по алфавиту сверху."""
        written = {}
        for status in st.FINDINGS:
            rows = sorted(
                (r for r in self.rows.values() if r["status"] == status),
                key=lambda r: (len(r["username"]), r["username"]),
            )
            path = self.out_dir / f"{status}.txt"
            if rows:
                with open(path, "w", encoding="utf-8") as f:
                    for line in st.FINDINGS_HEADERS[status].splitlines():
                        f.write(f"# {line}\n")
                    for r in rows:
                        extra = f"\t{st.fragment_link(r['username'])}" if status == st.FRAGMENT else ""
                        f.write(f"@{r['username']}\t{r['source']}\t{r['detail']}{extra}\n")
                written[status] = path
            elif path.exists():
                path.unlink()
        return written

    def close(self) -> None:
        self._file.close()
