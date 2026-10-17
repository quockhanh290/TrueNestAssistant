"""Deals / commission."""
from contextlib import closing
from .core import connect, _now
from .listings import get_listing
from .clients import list_clients
import uuid

from .validate import to_epoch, to_number



def count_listings_created(broker_id, start_ts, end_ts, path=None):
    with closing(connect(path)) as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM tg_listings WHERE broker_id = ?"
            " AND status != 'draft' AND created_at >= ? AND created_at < ?",
            (broker_id, start_ts, end_ts),
        ).fetchone()["c"]
        conn.close()
        return n


def deals_closed_between(broker_id, start_ts, end_ts, path=None):
    with closing(connect(path)) as conn:
        rows = conn.execute(
            "SELECT * FROM deals WHERE broker_id = ?"
            " AND closed_at >= ? AND closed_at < ? ORDER BY closed_at DESC",
            (broker_id, start_ts, end_ts),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def create_deal(broker_id, client_id=None, client_name="", listing_id=None,
                commission_vnd=None, closed_at=None, notes="", path=None):
    deal_id = "deal:" + uuid.uuid4().hex[:12]
    now = _now()
    # "15tr5" goes through the same money reader as the bot's commission step
    commission_vnd = to_number(commission_vnd, "commission_vnd", money=True)
    closed_at = to_epoch(closed_at, "closed_at")
    with closing(connect(path)) as conn:
        conn.execute(
            "INSERT INTO deals (id, broker_id, client_id, client_name, listing_id,"
            " commission_vnd, closed_at, notes, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (deal_id, broker_id, client_id, client_name, listing_id,
             commission_vnd, closed_at or now, notes, now, now),
        )
        conn.commit()
        conn.close()
        return deal_id


def get_deal(deal_id, path=None):
    with closing(connect(path)) as conn:
        row = conn.execute(
            "SELECT * FROM deals WHERE id = ?", (deal_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None


def list_deals(broker_id, start_ts=None, end_ts=None, limit=100, path=None):
    with closing(connect(path)) as conn:
        conds = ["broker_id = ?"]
        vals = [broker_id]
        if start_ts is not None:
            conds.append("closed_at >= ?")
            vals.append(start_ts)
        if end_ts is not None:
            conds.append("closed_at < ?")
            vals.append(end_ts)
        rows = conn.execute(
            "SELECT * FROM deals WHERE " + " AND ".join(conds) +
            " ORDER BY closed_at DESC LIMIT ?",
            (*vals, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def delete_deal(deal_id, path=None):
    with closing(connect(path)) as conn:
        cur = conn.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
        conn.commit()
        conn.close()
        return cur.rowcount > 0


def unpaid_deals(broker_id, path=None):
    """Unpaid deals (công nợ) for a broker, oldest first.

    Only deals with a positive commission count — zero/None commissions
    are not debts.
    """
    with closing(connect(path)) as conn:
        rows = conn.execute(
            "SELECT * FROM deals WHERE broker_id = ? AND paid = 0"
            " AND commission_vnd > 0 ORDER BY closed_at ASC",
            (broker_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def has_unpaid_debt(broker_id, path=None):
    """True if the broker has any unpaid deal (công nợ)."""
    with closing(connect(path)) as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM deals WHERE broker_id = ? AND paid = 0"
            " AND commission_vnd > 0",
            (broker_id,),
        ).fetchone()["c"]
        conn.close()
        return n > 0


def mark_deal_paid(deal_id, path=None):
    """Mark a deal as paid. Returns True if a row was updated."""
    with closing(connect(path)) as conn:
        cur = conn.execute(
            "UPDATE deals SET paid = 1, updated_at = ? WHERE id = ?",
            (_now(), deal_id),
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0


def deal_exists(broker_id, client_id, listing_id, path=None):
    """Already recorded a deal for this client+listing pair?"""
    with closing(connect(path)) as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM deals WHERE broker_id = ? AND client_id = ?"
            " AND listing_id = ?",
            (broker_id, client_id, listing_id),
        ).fetchone()["c"]
        conn.close()
        return n > 0


def suggested_deal_pairs(broker_id, path=None):
    """Candidate (client, listing) pairs for deal entry.

    Client must have status rented/deposited/negotiating AND have viewed at
    least one listing; the most recently viewed listing is paired.
    Pairs that already have a recorded deal are skipped.
    Sorted: rented first, then deposited, then negotiating.
    """
    rank = {"rented": 0, "deposited": 1, "negotiating": 2}
    out = []
    for c in list_clients(broker_id, path=path):
        st = c.get("status")
        if st not in rank:
            continue
        viewed = c.get("viewed_listings") or []
        if not viewed:
            continue
        listing_id = viewed[-1]
        l = get_listing(listing_id, path=path)
        if not l:
            continue
        if deal_exists(broker_id, c["id"], listing_id, path=path):
            continue
        out.append({"client": c, "listing": l, "rank": rank[st]})
    out.sort(key=lambda p: (p["rank"], -p["client"]["updated_at"]))
    return out
