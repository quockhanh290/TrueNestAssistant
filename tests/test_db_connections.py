"""Regression tests for deterministic SQLite connection cleanup."""
import ast
import gc
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

import test_flows  # noqa: F401,E402  (sets BOT_DB_PATH before config import)
import config  # noqa: E402
import db  # noqa: E402
from db import listings  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
# The connection factory intentionally returns an open connection to its caller.
ALLOW_OPEN = {("db/core.py", "connect")}


def _connect_call(node):
    return isinstance(node, ast.Call) and (
        isinstance(node.func, ast.Name) and node.func.id == "connect"
        or isinstance(node.func, ast.Attribute) and node.func.attr == "connect"
    )


def _assigned_name(call, parents):
    node = call
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.Assign) and node.value is call:
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                return node.targets[0].id
            return None
        if isinstance(node, (ast.stmt, ast.comprehension)):
            return None
    return None


def _calls_close(nodes, name):
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == name
        for root in nodes for node in ast.walk(root)
    )


def _guarded(call, function, parents):
    node = call
    while node is not function:
        node = parents[node]
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                expr = item.context_expr
                if (isinstance(expr, ast.Call)
                        and ((isinstance(expr.func, ast.Name)
                              and expr.func.id == "closing")
                             or (isinstance(expr.func, ast.Attribute)
                                 and expr.func.attr == "closing"))
                        and any(child is call for child in ast.walk(expr))):
                    return True

    name = _assigned_name(call, parents)
    if not name:
        return False
    for node in ast.walk(function):
        if isinstance(node, ast.Try) and node.finalbody:
            body_lines = [part.lineno for part in node.body if hasattr(part, "lineno")]
            if body_lines and call.lineno <= max(body_lines) and _calls_close(node.finalbody, name):
                return True
    return False


def test_every_connect_call_is_closed_on_exception():
    paths = sorted((ROOT / "db").glob("*.py")) + [ROOT / "followup.py"]
    scanned = []
    offenders = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {child: parent for parent in ast.walk(tree)
                   for child in ast.iter_child_nodes(parent)}
        rel = path.relative_to(ROOT).as_posix()
        for function in (node for node in ast.walk(tree)
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            calls = [node for node in ast.walk(function) if _connect_call(node)]
            if not calls:
                continue
            scanned.append((rel, function.name))
            if (rel, function.name) in ALLOW_OPEN:
                continue
            for call in calls:
                if not _guarded(call, function, parents):
                    offenders.append(f"{rel}:{function.name}:{call.lineno}")

    assert scanned, "AST scan unexpectedly found no functions calling connect()"
    assert not offenders, "unguarded connect() calls:\n" + "\n".join(offenders)


class _RaiseAfterWrite:
    """Connection proxy that fails after SQLite has acquired a write lock."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        result = self.connection.execute(sql, parameters)
        if sql.startswith("INSERT INTO tg_events"):
            raise RuntimeError("injected after write")
        return result

    def __getattr__(self, name):
        return getattr(self.connection, name)


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "connections.db"
    monkeypatch.setattr(config, "DB_PATH", str(path))
    db.init_db()
    db.get_or_create_broker(7001, username="connection-test")
    listing_id = db.create_listing(
        7001, raw_text="old", parsed={"deposit_months": 1.0},
        missing_fields=[], status="draft",
    )
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield path, listing_id
    finally:
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        gc.collect()


def test_failed_write_releases_lock_without_gc(database):
    path, listing_id = database
    real_connect = listings.connect

    def faulting_connect(db_path=None):
        return _RaiseAfterWrite(real_connect(db_path))

    with patch.object(listings, "connect", faulting_connect):
        with pytest.raises(RuntimeError, match="injected after write"):
            listings.update_listing_field(listing_id, "deposit_months", 2,
                                           path=str(path))

    fresh = sqlite3.connect(path, timeout=0.5)
    try:
        fresh.execute("UPDATE tg_listings SET raw_text = ? WHERE id = ?",
                      ("fresh writer", listing_id))
        fresh.commit()
    finally:
        fresh.close()


def test_description_none_stores_empty_string(database):
    path, listing_id = database
    assert listings.update_listing_field(
        listing_id, "description", None, path=str(path)
    ) is True
    assert db.get_listing(listing_id, path=str(path))["raw_text"] == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2, 2.0), ("2 th\u00e1ng", 2.0), ("2th", 2.0),
     ("1.5 th\u00e1ng", 1.5)],
)
def test_deposit_months_accepts_web_form_values(database, value, expected):
    path, listing_id = database
    assert listings.update_listing_field(
        listing_id, "deposit_months", value, path=str(path)
    ) is True
    assert db.get_listing(listing_id, path=str(path))["parsed"]["deposit_months"] == expected


@pytest.mark.parametrize("value", ["abc", "hai th\u00e1ng"])
def test_deposit_months_rejects_non_numbers(database, value):
    path, listing_id = database
    with pytest.raises(db.FieldError):
        listings.update_listing_field(
            listing_id, "deposit_months", value, path=str(path)
        )
