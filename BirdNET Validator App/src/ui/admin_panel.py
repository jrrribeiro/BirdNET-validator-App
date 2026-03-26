"""Gradio admin panel for managing projects and user assignments."""

from typing import List, Tuple

import gradio as gr

from src.auth.auth_service import AuthService, Session
from src.domain.models import Project, Role


class AdminPanelManager:
    """Management backend for the admin panel."""

    def __init__(self, auth_service: AuthService):
        """Initialize admin panel manager.

        Args:
            auth_service: AuthService instance
        """
        self.auth_service = auth_service
        self._projects: dict[str, Project] = {}  # project_slug -> Project
        self._user_project_assignments: dict[str, dict[str, str]] = {}  # username -> {project_slug -> role}

    def register_project(self, project: Project) -> bool:
        """Register a new project (idempotent).

        Args:
            project: Project to register

        Returns:
            True if new, False if already existed
        """
        if project.project_slug in self._projects:
            return False

        self._projects[project.project_slug] = project
        return True

    def list_projects(self) -> List[dict]:
        """List all projects as dictionaries for Gradio display.

        Returns:
            List of project dicts with slug, name, repo_id, active status
        """
        return [
            {
                "project_slug": p.project_slug,
                "name": p.name,
                "dataset_repo_id": p.dataset_repo_id,
                "active": p.active,
            }
            for p in self._projects.values()
        ]

    def get_project(self, project_slug: str) -> Project | None:
        """Get project by slug.

        Args:
            project_slug: Project slug

        Returns:
            Project if found, None otherwise
        """
        return self._projects.get(project_slug)

    def list_users_for_project(self, project_slug: str) -> List[dict]:
        """List all users assigned to a project.

        Args:
            project_slug: Project slug

        Returns:
            List of dicts with username and role
        """
        result = []
        for username in self.auth_service._user_access.keys():
            role = self.auth_service.get_user_role_for_project(username, project_slug)
            if role is not None:
                result.append({"username": username, "role": role.value})

        return result

    def assign_user_to_project(
        self, username: str, project_slug: str, role: str
    ) -> Tuple[bool, str]:
        """Assign a user to a project with a role.

        Args:
            username: Username
            project_slug: Project slug
            role: "admin" or "validator"

        Returns:
            Tuple of (success, message)
        """
        if project_slug not in self._projects:
            return False, f"Project '{project_slug}' not found"

        if role not in ["admin", "validator"]:
            return False, f"Invalid role: {role}"

        # Get or create user's project access
        if username not in self.auth_service._user_access:
            self.auth_service.register_user_project_access(username, {})

        access = self.auth_service._user_access[username]
        access.project_slugs[project_slug] = Role(role)

        return True, f"✅ Assigned {username} to {project_slug} as {role}"

    def remove_user_from_project(self, username: str, project_slug: str) -> Tuple[bool, str]:
        """Remove a user's access to a project.

        Args:
            username: Username
            project_slug: Project slug

        Returns:
            Tuple of (success, message)
        """
        if username not in self.auth_service._user_access:
            return False, f"User '{username}' not found"

        access = self.auth_service._user_access[username]
        if project_slug not in access.project_slugs:
            return False, f"User '{username}' is not assigned to project '{project_slug}'"

        del access.project_slugs[project_slug]
        return True, f"✅ Removed {username} from {project_slug}"

    def toggleproject_active(self, project_slug: str, active: bool) -> Tuple[bool, str]:
        """Enable or disable a project.

        Args:
            project_slug: Project slug
            active: Whether to activate or deactivate

        Returns:
            Tuple of (success, message)
        """
        if project_slug not in self._projects:
            return False, f"Project '{project_slug}' not found"

        self._projects[project_slug].active = active
        status = "activated" if active else "deactivated"
        return True, f"✅ Project {project_slug} {status}"


def create_admin_panel(admin_manager: AdminPanelManager, current_session: Session) -> gr.Blocks:
    """Create Gradio admin panel UI.

    Args:
        admin_manager: AdminPanelManager instance
        current_session: Current user's session

    Returns:
        Gradio Blocks with admin panel tabs
    """
    if current_session.role != Role.admin:
        with gr.Blocks() as restricted:
            gr.Markdown("❌ **Access Denied**\n\nOnly administrators can access this panel.")
        return restricted

    with gr.Blocks(title="BirdNET Admin Panel") as admin_block:
        gr.Markdown("# Admin Panel")
        gr.Markdown(f"Logged in as: **{current_session.username}** (Admin)")

        with gr.Tabs():
            # Projects Tab
            with gr.Tab("Projects"):
                gr.Markdown("## Manage Projects")

                with gr.Row():
                    with gr.Column(scale=2):
                        project_slug_input = gr.Textbox(
                            label="Project Slug",
                            placeholder="e.g., kenya-2024",
                            lines=1,
                        )
                        project_name_input = gr.Textbox(
                            label="Project Name",
                            placeholder="e.g., Kenya Survey 2024",
                            lines=1,
                        )

                    with gr.Column(scale=1):
                        repo_id_input = gr.Textbox(
                            label="HF Dataset Repo ID",
                            placeholder="e.g., org/dataset-name",
                            lines=1,
                        )

                project_message = gr.Markdown()

                # TODO: Implement create project button
                # create_project_button = gr.Button("Create Project", variant="primary")

                # Projects list
                with gr.Row():
                    refresh_projects_button = gr.Button("Refresh Projects List")
                    projects_table = gr.Dataframe(
                        value=admin_manager.list_projects(),
                        headers=["project_slug", "name", "dataset_repo_id", "active"],
                        interactive=False,
                    )

                refresh_projects_button.click(
                    fn=lambda: admin_manager.list_projects(),
                    outputs=[projects_table],
                )

            # Users Tab
            with gr.Tab("Users"):
                gr.Markdown("## Manage User Access")

                with gr.Row():
                    username_input = gr.Textbox(
                        label="Username",
                        placeholder="e.g., validator_001",
                        lines=1,
                    )

                    project_select = gr.Dropdown(
                        choices=[p["project_slug"] for p in admin_manager.list_projects()],
                        label="Project",
                    )

                    role_select = gr.Dropdown(
                        choices=["admin", "validator"],
                        value="validator",
                        label="Role",
                    )

                user_message = gr.Markdown()

                assign_button = gr.Button("Assign User", variant="primary")
                remove_button = gr.Button("Remove User", variant="stop")

                def assign_user(username: str, project_slug: str, role: str) -> str:
                    success, msg = admin_manager.assign_user_to_project(username, project_slug, role)
                    return msg

                def remove_user(username: str, project_slug: str) -> str:
                    success, msg = admin_manager.remove_user_from_project(username, project_slug)
                    return msg

                assign_button.click(
                    fn=assign_user,
                    inputs=[username_input, project_select, role_select],
                    outputs=[user_message],
                )

                remove_button.click(
                    fn=remove_user,
                    inputs=[username_input, project_select],
                    outputs=[user_message],
                )

                # Users per project view
                with gr.Row():
                    project_filter = gr.Dropdown(
                        choices=[p["project_slug"] for p in admin_manager.list_projects()],
                        label="View Users for Project",
                    )

                    users_table = gr.Dataframe(
                        value=[],
                        headers=["username", "role"],
                        interactive=False,
                    )

                def update_users_table(project_slug: str):
                    return admin_manager.list_users_for_project(project_slug)

                project_filter.change(
                    fn=update_users_table,
                    inputs=[project_filter],
                    outputs=[users_table],
                )

    return admin_block
