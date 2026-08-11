from __future__ import annotations

import asyncio
import io
from pathlib import Path

from pypdf import PdfWriter

from web_access.core.config import ParserSettings
from web_access.infrastructure.content.parser_isolation import SubprocessParserExecutor


def blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


async def main() -> None:
    settings = ParserSettings(
        child_temp_root=Path.cwd() / ".pdf-parser-smoke",
        child_timeout_seconds=10,
        child_memory_bytes=256 * 1024 * 1024,
    )
    executor = SubprocessParserExecutor(
        settings,
        allowed_parser_ids=frozenset({"pdf"}),
    )
    result = await executor.execute(
        "pdf",
        blank_pdf(),
        parameters={
            "max_pages": settings.pdf_max_pages,
            "max_page_chars": settings.pdf_max_page_chars,
            "max_output_chars": settings.pdf_max_output_chars,
            "max_metadata_chars": settings.pdf_max_metadata_chars,
            "max_content_stream_bytes": settings.pdf_max_content_stream_bytes,
            "max_resource_entries": settings.pdf_max_resource_entries,
        },
    )
    assert result.warnings[0].code == "pdf_native_text_unavailable"
    assert executor.hard_network_isolation
    print("Isolated PDF parser smoke passed under hard Linux process/network limits.")


if __name__ == "__main__":
    asyncio.run(main())
