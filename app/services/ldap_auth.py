"""OpenLDAP authentication helpers."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(frozen=True)
class LDAPAuthenticatedUser:
    external_id: str
    display_name: str
    is_admin: bool = False


def _first_attr(entry: Any, attr_name: str) -> str:
    if not attr_name:
        return ""
    value = getattr(entry, attr_name, None)
    if value is None:
        return ""
    try:
        values = value.values
        if values:
            return str(values[0]).strip()
    except Exception:
        pass
    try:
        return str(value.value).strip()
    except Exception:
        return str(value).strip()


def _render_filter(template: str, **values: str) -> str:
    from ldap3.utils.conv import escape_filter_chars

    safe_values = {key: escape_filter_chars(value or "") for key, value in values.items()}
    return template.format_map(_LDAPFilterContext(safe_values))


class _LDAPFilterContext(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _open_connection(server: Any, user: str = "", password: str = ""):
    from ldap3 import Connection

    conn = Connection(
        server,
        user=user or None,
        password=password or None,
        auto_bind=False,
        receive_timeout=settings.ldap_connect_timeout,
    )
    conn.open()
    if settings.ldap_start_tls:
        conn.start_tls()
    if not conn.bind():
        message = getattr(conn, "result", {}) or {}
        raise RuntimeError(f"LDAP bind failed: {message}")
    return conn


def _is_admin_member(search_conn: Any, user_dn: str, username: str) -> bool:
    admin_group_dn = settings.ldap_admin_group_dn.strip()
    if not admin_group_dn:
        return False

    group_base = settings.ldap_group_base_dn.strip() or admin_group_dn
    group_filter = _render_filter(
        settings.ldap_group_filter,
        user_dn=user_dn,
        username=username,
        user_id=username,
    )
    if not search_conn.search(
        group_base,
        group_filter,
        search_scope="SUBTREE",
        attributes=["cn"],
    ):
        return False

    expected = admin_group_dn.casefold()
    return any(getattr(entry, "entry_dn", "").casefold() == expected for entry in search_conn.entries)


def authenticate_ldap_user(username: str, password: str) -> LDAPAuthenticatedUser | None:
    """Authenticate a username/password against OpenLDAP and return mapped attributes."""
    username = username.strip()
    if not settings.ldap_enabled or not username or not password:
        return None
    if not settings.ldap_server_uri or not settings.ldap_user_base_dn:
        logger.error("LDAP is enabled but LDAP_SERVER_URI or LDAP_USER_BASE_DN is not configured")
        return None

    try:
        from ldap3 import ALL, SUBTREE, Server
    except ImportError as exc:
        logger.error("LDAP is enabled but ldap3 is not installed: %s", exc)
        return None

    search_conn = None
    user_conn = None
    try:
        server = Server(
            settings.ldap_server_uri,
            get_info=ALL,
            connect_timeout=settings.ldap_connect_timeout,
        )
        search_conn = _open_connection(
            server,
            settings.ldap_bind_dn,
            settings.ldap_bind_password,
        )
        user_filter = _render_filter(
            settings.ldap_user_filter,
            username=username,
            user_id=username,
        )
        attributes = {
            settings.ldap_user_id_attribute,
            settings.ldap_display_name_attribute,
        }
        attributes = {attribute for attribute in attributes if attribute}
        if not search_conn.search(
            settings.ldap_user_base_dn,
            user_filter,
            search_scope=SUBTREE,
            attributes=list(attributes),
        ):
            return None
        if not search_conn.entries:
            return None

        entry = search_conn.entries[0]
        user_dn = entry.entry_dn

        user_conn = _open_connection(server, user_dn, password)
        external_id = _first_attr(entry, settings.ldap_user_id_attribute) or username
        display_name = _first_attr(entry, settings.ldap_display_name_attribute) or external_id
        return LDAPAuthenticatedUser(
            external_id=external_id,
            display_name=display_name,
            is_admin=_is_admin_member(search_conn, user_dn, external_id),
        )
    except Exception as exc:
        logger.warning("LDAP authentication failed for %s: %s", username, exc)
        return None
    finally:
        for conn in (user_conn, search_conn):
            if conn is not None:
                try:
                    conn.unbind()
                except Exception:
                    pass
