"""QP identity verification for the e-signature re-authentication step at
approve()/reject() time (mcp_servers/review_actions.py) -- 21 CFR Part 11
requires the signer to re-authenticate with a credential at the moment of
signing, not merely be logged into a session. This module is that check:
a password re-entered at signing time, verified against db/init/04_qp_users.sql's
qp_users table, independent of whatever else the surrounding UI/CLI session
already trusts.
"""
from dataclasses import dataclass

import bcrypt

from mcp_servers.common import get_pg_connection


@dataclass
class QPIdentity:
    username: str
    display_name: str
    role: str


def list_active_qp_users() -> list[QPIdentity]:
    """For populating a "signing as" selector -- never exposes password_hash."""
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT username, display_name, role FROM qp_users WHERE active = true ORDER BY display_name"
        )
        rows = cur.fetchall()
    return [QPIdentity(username=r[0], display_name=r[1], role=r[2]) for r in rows]


def verify_qp_credentials(username: str, password: str) -> QPIdentity | None:
    """Checks a re-entered password against the stored hash for this
    signing attempt. Returns the verified identity on success, None on any
    failure (unknown username, inactive account, wrong password) -- callers
    must not distinguish these cases in user-facing messaging, to avoid
    leaking which usernames exist.
    """
    if not username or not password:
        return None

    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT password_hash, display_name, role FROM qp_users WHERE username = %s AND active = true",
            (username,),
        )
        row = cur.fetchone()

    if row is None:
        return None
    password_hash, display_name, role = row
    if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
        return None
    return QPIdentity(username=username, display_name=display_name, role=role)
