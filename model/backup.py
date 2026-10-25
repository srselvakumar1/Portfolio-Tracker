"""Automatic and manual backups of the portfolio database.

Backups are full copies made with SQLite's online-backup API, so they are
consistent even while the app is reading or writing. They live in a
"Backups" folder next to portfolio.db (for the installed app that is
~/Library/Application Support/PTracker/Backups).

File names look like  portfolio-2026-10-20_221530-daily.db  where the last
part says why the copy was made: daily, manual, or before-<action>.
"""

import os
import re
import sqlite3
import threading
from datetime import datetime

import model.database as database

DAILY_KEEP = 30    # one a day on launch, so about a month of history
SAFETY_KEEP = 30   # copies taken right before a delete, wipe, import or restore
# Manual backups ("Back up now") are never deleted automatically.

_NAME_RE = re.compile(r"^portfolio-(\d{4}-\d{2}-\d{2})_(\d{6})-([a-z0-9-]+)\.db$")
_lock = threading.Lock()


def backup_dir() -> str:
    """Return the Backups folder, creating it if needed."""
    path = os.path.join(os.path.dirname(database.DB_PATH), "Backups")
    os.makedirs(path, exist_ok=True)
    return path


def _copy_db(src_path: str, dst_path: str) -> None:
    """Copy one SQLite database into another with the online-backup API."""
    src = sqlite3.connect(src_path, timeout=15.0)
    try:
        dst = sqlite3.connect(dst_path, timeout=15.0)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create_backup(reason: str = "manual") -> str:
    """Copy the live database into the Backups folder and return the new path.

    Raises an exception if the copy fails or does not pass SQLite's quick check,
    so callers can refuse to go ahead with a risky action.
    """
    reason = re.sub(r"[^a-z0-9-]+", "-", reason.lower()).strip("-") or "manual"
    with _lock:
        folder = backup_dir()
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        final = os.path.join(folder, f"portfolio-{stamp}-{reason}.db")
        n = 2
        while os.path.exists(final):
            final = os.path.join(folder, f"portfolio-{stamp}-{reason}-{n}.db")
            n += 1
        tmp = final + ".part"

        try:
            _copy_db(database.DB_PATH, tmp)
            conn = sqlite3.connect(tmp)
            try:
                # A backup should be one self-contained file, with no -wal beside it
                conn.execute("PRAGMA journal_mode=DELETE")
                result = conn.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                conn.close()
            if result != "ok":
                raise RuntimeError(f"the copy failed SQLite's check ({result})")
            os.replace(tmp, final)
        except Exception:
            for leftover in (tmp, tmp + "-journal"):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
            raise

        _prune()
        return final


def safety_backup(action: str) -> str:
    """Back up right before a risky action, e.g. safety_backup("wipe").

    Raises on failure; the caller should then cancel the action and tell the user.
    """
    return create_backup(f"before-{action}")


def daily_backup_if_due() -> str | None:
    """Make today's automatic backup, unless one already exists.

    An empty database (no trades) is skipped, so a wiped database does not
    push the older, useful backups out of the 30-day window.
    """
    if not database.DB_PATH or not os.path.exists(database.DB_PATH):
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    for info in list_backups():
        if info["reason"] == "daily" and info["when"].strftime("%Y-%m-%d") == today:
            return None
    try:
        conn = sqlite3.connect(database.DB_PATH, timeout=15.0)
        try:
            trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if trade_count == 0:
        return None
    return create_backup("daily")


def list_backups() -> list[dict]:
    """Return the backups, newest first, as dicts with path, name, when, reason, size."""
    folder = backup_dir()
    out = []
    for name in os.listdir(folder):
        m = _NAME_RE.match(name)
        if not m:
            continue
        try:
            when = datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M%S")
        except ValueError:
            continue
        reason = re.sub(r"-\d+$", "", m.group(3))  # drop the "-2" added for same-second copies
        path = os.path.join(folder, name)
        out.append({
            "path": path,
            "name": name,
            "when": when,
            "reason": reason,
            "size": os.path.getsize(path),
        })
    out.sort(key=lambda b: b["when"], reverse=True)
    return out


def _prune() -> None:
    """Keep the newest DAILY_KEEP daily and SAFETY_KEEP before-* backups."""
    daily = []
    safety = []
    for info in list_backups():
        if info["reason"] == "daily":
            daily.append(info)
        elif info["reason"].startswith("before-"):
            safety.append(info)
    for info in daily[DAILY_KEEP:] + safety[SAFETY_KEEP:]:
        try:
            os.remove(info["path"])
        except OSError as e:
            print(f"[Backup] Could not remove old backup {info['name']}: {e}")


def describe_backup(path: str) -> dict:
    """Check that a file is a usable PTracker database and summarise it.

    Returns {"trades": int, "brokers": int, "first_date": str, "last_date": str}.
    Raises ValueError with a plain-English message if the file can't be used.
    """
    if not os.path.isfile(path):
        raise ValueError("That file doesn't exist.")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        raise ValueError("That file isn't a PTracker database.")
    try:
        try:
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("That backup is damaged, so it can't be restored.")
            trades, first_date, last_date = conn.execute(
                "SELECT COUNT(*), MIN(date), MAX(date) FROM trades"
            ).fetchone()
            brokers = conn.execute("SELECT COUNT(*) FROM brokers").fetchone()[0]
        except sqlite3.DatabaseError:
            raise ValueError("That file isn't a PTracker database.")
    finally:
        conn.close()
    return {
        "trades": int(trades or 0),
        "brokers": int(brokers or 0),
        "first_date": first_date or "",
        "last_date": last_date or "",
    }


def restore_backup(path: str) -> str:
    """Replace the live database's contents with a backup.

    The current data is backed up first (reason "before-restore"), and that
    path is returned so the user can undo the restore. The copy goes through
    SQLite, so connections the app already holds stay valid and see the
    restored data. Afterwards the caller should re-run the schema setup and
    rebuild holdings, since the backup may come from an older version.
    """
    describe_backup(path)  # raises ValueError if unusable
    if os.path.abspath(path) == os.path.abspath(database.DB_PATH):
        raise ValueError("That is the live database, not a backup.")
    undo_path = safety_backup("restore")
    with _lock:
        _copy_db(path, database.DB_PATH)
    return undo_path
