from __future__ import annotations

import asyncio
import json
from pathlib import Path

from web_access.core.config import ParserSettings
from web_access.infrastructure.content.parser_isolation import SubprocessParserExecutor


async def main() -> None:
    async def close_control_connection(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(close_control_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = ParserSettings(
        child_temp_root=Path.cwd() / ".parser-network-smoke",
        child_timeout_seconds=5,
        child_memory_bytes=256 * 1024 * 1024,
    )
    executor = SubprocessParserExecutor(
        settings,
        allowed_parser_ids=frozenset({"test_network_probe"}),
        test_mode=True,
    )
    try:
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        result = await executor.execute(
            "test_network_probe",
            b"",
            parameters={"host": "127.0.0.1", "port": port},
        )
        assert json.loads(result.representations[0].data) == {"blocked": True}
        assert executor.hard_network_isolation
        print(
            "Parser child seccomp no-network filter blocked a parent-reachable "
            f"TCP endpoint at 127.0.0.1:{port}."
        )
    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
