"""FastMCP Streamable HTTP server factory."""

from fastmcp import FastMCP

from web_access.application.common.auth import AuthProvider
from web_access.transport.mcp.auth import FastMcpAuthAdapter


def create_mcp_server(auth_provider: AuthProvider) -> FastMCP:
    """Create the intentionally empty v0.1 production catalog."""

    return FastMCP(
        name="Web Access",
        version="0.1.0",
        instructions="Service Foundation: production business tools are not registered yet.",
        auth=FastMcpAuthAdapter(auth_provider),
        mask_error_details=True,
        strict_input_validation=True,
    )
