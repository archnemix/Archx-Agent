"""Open one workspace and dispatch models subcommands."""

from __future__ import annotations

import argparse
from archx_agent.interfaces.cli.support import _workspace, EXIT_USAGE

from .catalogue import handle_list
from .catalogue import handle_discover
from .registration import handle_add_http
from .registration import handle_sdks
from .registration import handle_add_sdk
from .registration import handle_add_gemini
from .registration import handle_add_scripted
from .catalogue import handle_show
from .catalogue import handle_enable
from .catalogue import handle_verify
from .catalogue import handle_prefer
from .catalogue import handle_remove
from .routing import handle_route
from .routing import handle_probe
from .routing import handle_capabilities
from .catalogue import handle_storage
from .catalogue import handle_compare

HANDLERS = {'list': handle_list, 'discover': handle_discover, 'add-http': handle_add_http, 'sdks': handle_sdks, 'add-sdk': handle_add_sdk, 'add-gemini': handle_add_gemini, 'add-scripted': handle_add_scripted, 'show': handle_show, 'enable': handle_enable, 'disable': handle_enable, 'verify': handle_verify, 'prefer': handle_prefer, 'remove': handle_remove, 'route': handle_route, 'probe': handle_probe, 'capabilities': handle_capabilities, 'storage': handle_storage, 'compare': handle_compare}

def cmd_models(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        command = args.models_command
        handler = HANDLERS.get(command)
        if handler is not None:
            result = handler(args, ws, command)
            if result is not None:
                return result
    return EXIT_USAGE
