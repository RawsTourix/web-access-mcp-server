"""Route parser execution by descriptor policy, never by caller library name."""

from web_access.application.content.models import ContentInspection, NativeParserOutput
from web_access.application.content.ports import IsolatedParserExecutor, NativeParser
from web_access.core.config import ParserSettings
from web_access.domain.content import ContentObject, ParserExecutionMode
from web_access.infrastructure.content.parsers.executor import InlineNativeParserExecutor


class RoutingNativeParserExecutor:
    def __init__(
        self,
        *,
        settings: ParserSettings,
        isolated: IsolatedParserExecutor,
        inline: InlineNativeParserExecutor | None = None,
    ) -> None:
        self._settings = settings
        self._isolated = isolated
        self._inline = inline or InlineNativeParserExecutor()

    async def execute(
        self,
        parser: NativeParser,
        source: ContentObject,
        inspection: ContentInspection,
        data: bytes,
    ) -> NativeParserOutput:
        descriptor = parser.descriptor
        if descriptor.execution_mode is ParserExecutionMode.INLINE:
            return await self._inline.execute(parser, source, inspection, data)
        return await self._isolated.execute(
            descriptor.capability,
            data,
            parameters={
                "max_pages": self._settings.pdf_max_pages,
                "max_page_chars": self._settings.pdf_max_page_chars,
                "max_output_chars": self._settings.pdf_max_output_chars,
                "max_metadata_chars": self._settings.pdf_max_metadata_chars,
                "max_content_stream_bytes": self._settings.pdf_max_content_stream_bytes,
                "max_resource_entries": self._settings.pdf_max_resource_entries,
            },
        )
