import secrets

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services import ldap_auth
from app.time_utils import utc_now

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def get_user_by_user_id(db: Session, user_id: str) -> User | None:
    """Get a user by their 6-digit user ID."""
    stmt = select(User).where(User.user_id == user_id)
    return db.execute(stmt).scalar_one_or_none()


def get_user_by_external_auth(db: Session, provider: str, external_id: str) -> User | None:
    """Get a user linked to an external authentication provider."""
    stmt = (
        select(User)
        .where(User.external_auth_provider == provider)
        .where(User.external_auth_id == external_id)
    )
    return db.execute(stmt).scalar_one_or_none()


def get_user_by_id(db: Session, id: int) -> User | None:
    """Get a user by their internal ID."""
    stmt = select(User).where(User.id == id)
    return db.execute(stmt).scalar_one_or_none()


def get_users(
    db: Session, skip: int = 0, limit: int = 100, include_inactive: bool = False
) -> list[User]:
    """Get a list of users."""
    stmt = select(User)
    if not include_inactive:
        stmt = stmt.where(User.is_active == True)
    stmt = stmt.offset(skip).limit(limit)
    return list(db.execute(stmt).scalars().all())


def create_user(db: Session, user_data: UserCreate, user_id: str | None = None) -> User:
    """Create a new user. user_id is auto-generated if not specified."""
    if user_id:
        if not user_id.isdigit() or len(user_id) != 6:
            raise ValueError("user_id は6桁の数字で指定してください")
    else:
        while True:
            user_id = User.generate_user_id()
            if not get_user_by_user_id(db, user_id):
                break

    user = User(
        user_id=user_id,
        password_hash=get_password_hash(user_data.password),
        display_name=user_data.display_name,
        role=user_data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _new_unlinked_password_hash() -> str:
    return get_password_hash(secrets.token_urlsafe(32))


def _generate_unused_user_id(db: Session) -> str:
    while True:
        user_id = User.generate_user_id()
        if not get_user_by_user_id(db, user_id):
            return user_id


def _ldap_default_role() -> UserRole:
    try:
        return UserRole(settings.ldap_default_role)
    except ValueError:
        return UserRole.USER


def _get_or_create_ldap_user(
    db: Session,
    ldap_user: ldap_auth.LDAPAuthenticatedUser,
) -> User | None:
    user = get_user_by_external_auth(db, "ldap", ldap_user.external_id)

    if user:
        if not user.is_active:
            return None
        user.display_name = ldap_user.display_name or user.display_name
        user.last_login_at = utc_now()
        db.commit()
        db.refresh(user)
        return user

    user = User(
        user_id=_generate_unused_user_id(db),
        external_auth_provider="ldap",
        external_auth_id=ldap_user.external_id,
        password_hash=_new_unlinked_password_hash(),
        display_name=ldap_user.display_name or ldap_user.external_id,
        role=_ldap_default_role(),
        is_active=True,
        last_login_at=utc_now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _authenticate_linked_ldap_user(db: Session, user: User, password: str) -> User | None:
    if (
        not user.is_active
        or user.external_auth_provider != "ldap"
        or not user.external_auth_id
    ):
        return None

    ldap_user = ldap_auth.authenticate_ldap_user(user.external_auth_id, password)
    if not ldap_user:
        return None
    return _get_or_create_ldap_user(db, ldap_user)


def authenticate_user(db: Session, user_id: str, password: str) -> User | None:
    """Authenticate a user and return the user object if successful."""
    user_id = user_id.strip()
    user = get_user_by_user_id(db, user_id) if user_id.isdigit() and len(user_id) == 6 else None
    if user:
        if user.external_auth_provider == "ldap":
            return _authenticate_linked_ldap_user(db, user, password)
        if user.is_active and verify_password(password, user.password_hash):
            user.last_login_at = utc_now()
            db.commit()
            return user

    ldap_user = ldap_auth.authenticate_ldap_user(user_id, password)
    if ldap_user:
        return _get_or_create_ldap_user(db, ldap_user)

    return None


def update_user_password(db: Session, user: User, new_password: str) -> User:
    """Update a user's password."""
    user.password_hash = get_password_hash(new_password)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user: User,
    display_name: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
) -> User:
    """Update user information."""
    if display_name is not None and user.external_auth_provider != "ldap":
        user.display_name = display_name
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user


def create_admin_user(
    db: Session,
    display_name: str,
    password: str,
    user_id: str | None = None,
    overwrite: bool = False,
) -> User:
    """Create an admin user. If overwrite=True and user_id exists, reset the password."""
    if overwrite and user_id:
        existing = get_user_by_user_id(db, user_id)
        if existing:
            existing.password_hash = get_password_hash(password)
            existing.display_name = display_name
            existing.role = UserRole.ADMIN
            existing.is_active = True
            db.commit()
            db.refresh(existing)
            return existing

    user_data = UserCreate(
        display_name=display_name,
        password=password,
        role=UserRole.ADMIN,
    )
    return create_user(db, user_data, user_id=user_id)
