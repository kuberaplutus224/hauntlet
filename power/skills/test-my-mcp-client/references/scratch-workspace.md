# The scratch client workspace

A scratch client workspace is a new, empty directory made for one run. The
user opens it in a separate Kiro window as the client under test. It is the
only place this power ever puts a room's MCP server, or any config that points
a client at a room.

## Checks before writing

Resolve the path from `mktemp -d` to an absolute, symlink-free path (on macOS
`/var/…` resolves to `/private/var/…`). Then all of these must hold, or stop
and write nothing:

1. It is not the user's workspace root, and not inside it.
2. It is not `~/.kiro`, and not inside it.
3. It is not the range directory, and not inside it. The client must not be
   able to read the range's own files (its event store and fact logs).
4. It is empty.

Never reuse a scratch workspace for a second run. Make a new one.

## The server entry

Replace `RUN_ID` with the run ID and `/absolute/path/to/range` with the range
directory's absolute path. For `poltergeist-legacy`, change the server name to
`hauntlet_poltergeist_legacy` and the room to `poltergeist-legacy`.

### No checkout (`uvx`)

```json
{
  "mcpServers": {
    "hauntlet_poltergeist": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/kuberaplutus224/hauntlet",
        "hauntlet", "mcp", "serve", "--room", "poltergeist", "--run=RUN_ID"
      ],
      "env": {
        "HAUNTLET_DB": "/absolute/path/to/range/.hauntlet/range.db",
        "HAUNTLET_BASE_URL": "http://127.0.0.1:8666"
      }
    }
  }
}
```

### Local checkout

```json
{
  "mcpServers": {
    "hauntlet_poltergeist": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/checkout",
        "run", "hauntlet", "mcp", "serve", "--room", "poltergeist", "--run=RUN_ID"
      ],
      "env": {
        "HAUNTLET_DB": "/absolute/path/to/checkout/.hauntlet/range.db",
        "HAUNTLET_BASE_URL": "http://127.0.0.1:8666"
      }
    }
  }
}
```

## Why the power ships no MCP server

Kiro starts a power's MCP servers whenever the power is active. A room server
needs a run ID that is created per run, and a room server is hostile by
design. Bundled into the power, it would run inside the user's own Kiro. So
the power writes it only here, per run, and removes it afterwards.

## One session per run

The first `mcp serve` for a run owns that run's workspace. If the client
restarts or reconnects after it has used the tools, the server refuses. Then
make a new run (and a new scratch workspace) and begin again.

Once the run is finalized or expires, the server stops by itself.
