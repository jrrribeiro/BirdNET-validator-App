"""AuthService: User authentication, session management, and project ACL."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import uuid

from src.domain.models import Role, User


@dataclass
class UserProjectAccess:
    """Maps a user to projects with specific roles."""

    username: str
    project_slugs: Dict[str, Role]  # Maps project_slug -> role (admin or validator)
    is_active: bool = True


@dataclass
class Session:
    """Represents an authenticated user session."""

    session_id: str
    username: str
    role: Role
    authorized_projects: List[str]  # Projects this user can access
    created_at: datetime
    last_activity: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.utcnow() > self.expires_at

    def update_activity(self, ttl_minutes: int = 120) -> None:
        """Update last activity timestamp and extend expiration."""
        self.last_activity = datetime.utcnow()
        self.expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)


class AuthService:
    """Manages user authentication, sessions, and project access control."""

    def __init__(self, session_ttl_minutes: int = 120):
        """Initialize AuthService with session TTL.

        Args:
            session_ttl_minutes: Session time-to-live in minutes (default: 2 hours)
        """
        self.session_ttl_minutes = session_ttl_minutes
        self._sessions: Dict[str, Session] = {}  # session_id -> Session
        self._user_access: Dict[str, UserProjectAccess] = {}  # username -> UserProjectAccess

    def register_user_project_access(
        self, username: str, project_access: Dict[str, Role]
    ) -> None:
        """Register or update a user's access to projects.

        Args:
            username: User name
            project_access: Dict mapping project_slug to Role (admin or validator)
        """
        self._user_access[username] = UserProjectAccess(
            username=username,
            project_slugs=project_access,
            is_active=True,
        )

    def login(self, username: str) -> Optional[Session]:
        """Authenticate a user and create a new session.

        Args:
            username: User name to authenticate

        Returns:
            Session if user exists and is active, None otherwise
        """
        if username not in self._user_access:
            return None

        access = self._user_access[username]
        if not access.is_active:
            return None

        # Determine highest role across all projects (admin > validator)
        role = Role.validator
        for proj_role in access.project_slugs.values():
            if proj_role == Role.admin:
                role = Role.admin
                break

        session_id = str(uuid.uuid4())
        now = datetime.utcnow()
        session = Session(
            session_id=session_id,
            username=username,
            role=role,
            authorized_projects=list(access.project_slugs.keys()),
            created_at=now,
            last_activity=now,
            expires_at=now + timedelta(minutes=self.session_ttl_minutes),
        )

        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve an active session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session if valid and not expired, None otherwise
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None

        if session.is_expired():
            self._sessions.pop(session_id, None)
            return None

        session.update_activity(self.session_ttl_minutes)
        return session

    def logout(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: Session ID to invalidate
        """
        self._sessions.pop(session_id, None)

    def is_user_authorized_for_project(self, username: str, project_slug: str) -> bool:
        """Check if a user has access to a specific project.

        Args:
            username: User name
            project_slug: Project slug

        Returns:
            True if user has access (admin or validator), False otherwise
        """
        access = self._user_access.get(username)
        if access is None or not access.is_active:
            return False

        return project_slug in access.project_slugs

    def get_user_role_for_project(self, username: str, project_slug: str) -> Optional[Role]:
        """Get the specific role a user has for a project.

        Args:
            username: User name
            project_slug: Project slug

        Returns:
            Role if user has access, None otherwise
        """
        access = self._user_access.get(username)
        if access is None or not access.is_active:
            return None

        return access.project_slugs.get(project_slug)

    def list_user_projects(self, username: str) -> List[str]:
        """List all projects a user has access to.

        Args:
            username: User name

        Returns:
            List of project slugs
        """
        access = self._user_access.get(username)
        if access is None or not access.is_active:
            return []

        return list(access.project_slugs.keys())

    def cleanup_expired_sessions(self) -> None:
        """Remove all expired sessions (maintenance cleanup)."""
        now = datetime.utcnow()
        expired = [
            sid for sid, session in self._sessions.items() if session.is_expired()
        ]
        for sid in expired:
            self._sessions.pop(sid)

    def set_user_active(self, username: str, active: bool) -> None:
        """Enable or disable a user account.

        Args:
            username: User name
            active: Whether the user should be active
        """
        if username in self._user_access:
            self._user_access[username].is_active = active
