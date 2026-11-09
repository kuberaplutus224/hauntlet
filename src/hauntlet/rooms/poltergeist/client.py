"""In-process MCP client helper for the reference agents (Requirement 9.4, 10.2, D4).

The core runner calls ``agent.run(materials, tools)`` with a ``ToolBox``, not an
MCP session. ``connect(materials, tools)`` bridges the two:

1. it looks the run's ``PoltergeistServer`` up in the process-local registry
   that ``PoltergeistRoom.setup`` filled, keyed by ``env["POLTERGEIST_RUN"]``
   and the room name;
2. it binds the server's relay fetcher to ``tools.fetch`` and its scratch writer
   to ``tools.write_file``, so every relay is confined to the run's canary
   endpoint (and reaches ``RangeService.fetch_local``) and every write to the
   scratch workspace, exactly as the ToolBox confines the agents themselves;
3. it connects an SDK ``Client`` over ``InMemoryTransport``: no socket, no
   third-party client. ``poltergeist`` speaks ``mode="2026-07-28"``,
   ``poltergeist-legacy`` ``mode="legacy"`` (the 2025-11-25 handshake).

The SDK client is async and the agents are synchronous, so the helper runs the
client on a private event loop in a worker thread (an anyio blocking portal)
and each public method is one blocking, deadline-bounded step. The connection
stays open across steps until ``close()``.

``PoltergeistClient`` is a thin scripted wrapper:

* ``approve()``: on 2026-07-28, open ``subscriptions/listen`` with
  ``toolsListChanged``; then ``tools/list``. Returns the descriptions.
* ``call(tool, **args)``: one ``tools/call``; returns the reply text, raises
  ``ToolCallError`` on an ``isError`` result.
* ``on_change(timeout)``: block until a change signal arrives that has not been
  consumed yet (``notifications/tools/list_changed`` on legacy, a
  ``ToolsListChanged`` subscription event on 2026-07-28), then consume it.
* ``relist()``: ``tools/list`` again. Returns the descriptions.
* ``descriptions()``: the descriptions from the latest listing.

``call`` refuses to run before ``approve``. Listing first is what every client
does, and it also keeps the SDK from issuing a hidden ``tools/list`` after the
first call (``validate_tool_result`` refreshes an empty output-schema cache),
which would re-fetch the rug-pulled set behind the agent's back.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from typing import Any

import anyio
import mcp_types as types
from anyio.abc import TaskGroup, TaskStatus
from anyio.from_thread import BlockingPortal, start_blocking_portal
from mcp.client._memory import InMemoryTransport
from mcp.client.client import Client
from mcp.client.subscriptions import listen as client_listen
from mcp.server.subscriptions import ToolsListChanged

from hauntlet.core.room import RoomMaterials
from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms.poltergeist.room import ENV_RUN, server_for
from hauntlet.rooms.poltergeist.server import PoltergeistServer

#: Deadline for every blocking step, so a protocol fault fails instead of hanging.
TIMEOUT = 10.0

#: SDK client mode per change-signal mechanism (``RevisionSettings.signal``).
_MODES = {"subscriptions_listen": "2026-07-28", "list_changed": "legacy"}


class ToolCallError(RuntimeError):
    """A ``tools/call`` came back with ``isError``; the message is the reply text."""


def _text_of(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


class PoltergeistClient:
    """A synchronous, scripted MCP client for one room of one run."""

    def __init__(self, server: PoltergeistServer, *, timeout: float = TIMEOUT) -> None:
        signal = server.config.revision.signal
        if signal not in _MODES:
            raise ValueError(f"no client mode for change signal {signal!r}")
        self._server = server
        self._modern = signal == "subscriptions_listen"
        self.mode = _MODES[signal]
        self.timeout = timeout

        self._client: Client | None = None
        self._tg: TaskGroup | None = None
        self._approved = False
        self._subscribed = False
        self._descriptions: dict[str, str | None] = {}
        self._schemas: dict[str, dict[str, Any]] = {}  # D20: from the latest listing

        # Change signals arrive on the portal thread; on_change waits on the caller's.
        self._cond = threading.Condition()
        self._signals = 0
        self._consumed = 0

        self._stack = ExitStack()
        try:
            self._portal: BlockingPortal = self._stack.enter_context(start_blocking_portal())
            self._stack.enter_context(self._portal.wrap_async_context_manager(self._session()))
        except BaseException:
            self._stack.close()
            raise

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def __enter__(self) -> PoltergeistClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the subscription, the connection and the private loop. Idempotent."""
        self._stack.close()

    @property
    def protocol_version(self) -> str | None:
        """The negotiated protocol revision."""
        return None if self._client is None else self._client.protocol_version

    @property
    def subscribed(self) -> bool:
        """True once a 2026-07-28 ``subscriptions/listen`` stream is open and honored."""
        return self._subscribed

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[None]:
        client = Client(
            InMemoryTransport(self._server.server, raise_exceptions=True),
            mode=self.mode,
            message_handler=None if self._modern else self._on_message,
            raise_exceptions=True,
        )
        async with client:
            try:
                async with anyio.create_task_group() as tg:
                    self._client, self._tg = client, tg
                    try:
                        yield
                    finally:
                        tg.cancel_scope.cancel()
            finally:
                self._client = self._tg = None

    def _run(self, fn: Any, *args: Any) -> Any:
        async def step() -> Any:
            with anyio.fail_after(self.timeout):
                return await fn(*args)

        return self._portal.call(step)

    def _require_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("the Poltergeist client is closed")
        return self._client

    # ------------------------------------------------------------------ #
    # change signal
    # ------------------------------------------------------------------ #

    def _note_change(self) -> None:
        with self._cond:
            self._signals += 1
            self._cond.notify_all()

    async def _on_message(self, message: Any) -> None:
        if isinstance(message, types.ToolListChangedNotification):
            self._note_change()

    async def _listen(self, *, task_status: TaskStatus[bool]) -> None:
        client = self._require_client()
        async with client_listen(client.session, tools_list_changed=True) as subscription:
            task_status.started(subscription.honored.tools_list_changed is True)
            async for event in subscription:
                if isinstance(event, ToolsListChanged):
                    self._note_change()

    @property
    def changes(self) -> int:
        """How many change signals have arrived so far."""
        with self._cond:
            return self._signals

    def on_change(self, timeout: float | None = None) -> None:
        """Block until an unconsumed change signal arrives, then consume it.

        Raises ``TimeoutError`` if none arrives within ``timeout`` seconds
        (default: the client's step deadline).
        """
        wait = self.timeout if timeout is None else timeout
        with self._cond:
            if not self._cond.wait_for(lambda: self._signals > self._consumed, timeout=wait):
                raise TimeoutError(f"no tool-list change signal within {wait}s")
            self._consumed += 1

    # ------------------------------------------------------------------ #
    # scripted steps
    # ------------------------------------------------------------------ #

    async def _list(self) -> dict[str, str | None]:
        result = await self._require_client().list_tools()
        self._descriptions = {tool.name: tool.description for tool in result.tools}
        self._schemas = {tool.name: copy.deepcopy(dict(tool.input_schema)) for tool in result.tools}
        return dict(self._descriptions)

    async def _approve(self) -> dict[str, str | None]:
        if self._modern and not self._subscribed:
            assert self._tg is not None
            honored = await self._tg.start(self._listen)
            if not honored:
                raise RuntimeError("the server did not honor the toolsListChanged subscription")
            self._subscribed = True
        listed = await self._list()
        self._approved = True
        return listed

    def approve(self) -> dict[str, str | None]:
        """Subscribe to tool-list changes (2026-07-28 only), then list the tools."""
        return self._run(self._approve)

    def relist(self) -> dict[str, str | None]:
        """Re-fetch ``tools/list``; returns and remembers the descriptions."""
        return self._run(self._list)

    def descriptions(self) -> dict[str, str | None]:
        """Tool name -> description from the latest listing (empty before ``approve``)."""
        return dict(self._descriptions)

    def input_schemas(self) -> dict[str, dict[str, Any]]:
        """Tool name -> ``inputSchema`` from the latest listing (approved change D20).

        Read-only: returns a deep copy, ``{}`` before ``approve``. A real client's
        model sees the same schemas; the demo agent uses them to fill a call's
        arguments without hard-coding argument names.
        """
        return copy.deepcopy(self._schemas)

    async def _call(self, tool: str, args: dict[str, Any]) -> types.CallToolResult:
        return await self._require_client().call_tool(tool, args)

    def call(self, tool: str, **args: Any) -> str:
        """Call ``tool`` with keyword ``args``; returns the reply text.

        Raises ``ToolCallError`` when the server answers with ``isError``.
        """
        if not self._approved:
            raise RuntimeError("call approve() before calling tools")
        result: types.CallToolResult = self._run(self._call, tool, dict(args))
        text = _text_of(result)
        if result.is_error:
            raise ToolCallError(text)
        return text


def connect(materials: RoomMaterials, tools: ToolBox, *, timeout: float = TIMEOUT) -> PoltergeistClient:
    """Connect to the run's Poltergeist server with the agent's ToolBox as its I/O.

    Looks the server up by ``materials.env["POLTERGEIST_RUN"]`` and
    ``materials.room``; raises ``KeyError`` if the room was not set up in this
    process. Relays go through ``tools.fetch`` and scratch writes through
    ``tools.write_file``.
    """
    if ENV_RUN not in materials.env:
        raise KeyError(f"{materials.room}: materials carry no {ENV_RUN}")
    server = server_for(materials)
    server.bind_io(tools.fetch, tools.write_file)
    return PoltergeistClient(server, timeout=timeout)


__all__ = ["PoltergeistClient", "ToolCallError", "connect", "TIMEOUT"]
