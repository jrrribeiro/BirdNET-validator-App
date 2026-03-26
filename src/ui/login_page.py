"""Gradio login page component for multi-project authorization."""

from typing import Optional, Tuple

import gradio as gr

from src.auth.auth_service import AuthService, Session


def create_login_page(auth_service: AuthService) -> Tuple[gr.Blocks, gr.Textbox, gr.Textbox, gr.Button, gr.Markdown]:
    """Create a Gradio login page with username input and session tracking.

    Args:
        auth_service: AuthService instance for login validation

    Returns:
        Tuple of (login_block, username_input, session_output, login_button, error_message)
    """

    with gr.Blocks(title="BirdNET-Validator-App - Login") as login_block:
        gr.Markdown("# BirdNET Validation Platform")
        gr.Markdown("Login to access multi-project validation workflows")

        username_input = gr.Textbox(
            label="Username",
            placeholder="Enter your username",
            lines=1,
        )

        error_message = gr.Markdown()

        login_button = gr.Button("Login", variant="primary", scale=1)

        session_output = gr.Textbox(
            label="Session ID",
            interactive=False,
            visible=False,
        )

        def perform_login(username: str) -> Tuple[str, str]:
            """Attempt login and return session ID or error message.

            Args:
                username: Username to authenticate

            Returns:
                Tuple of (session_id, error_message)
            """
            if not username or not username.strip():
                return "", "❌ Please enter a username"

            username = username.strip()
            session = auth_service.login(username)

            if session is None:
                return "", f"❌ User '{username}' not found or inactive"

            return session.session_id, f"✅ Welcome, {username}! (Admin)" if session.role.value == "admin" else f"✅ Welcome, {username}! (Validator)"

        login_button.click(
            fn=perform_login,
            inputs=[username_input],
            outputs=[session_output, error_message],
        )

    return login_block, username_input, session_output, login_button, error_message
