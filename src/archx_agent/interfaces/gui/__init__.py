"""The local web GUI (M29): a client of the application layer, not a second one."""

from archx_agent.interfaces.gui.server import ApiError, GuiApi, GuiServer, Request, Response

__all__ = ["ApiError", "GuiApi", "GuiServer", "Request", "Response"]
