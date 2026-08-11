"""Direct executor for parsers accepted for in-process v0.3 execution."""

from web_access.application.content.models import ContentInspection, NativeParserOutput
from web_access.application.content.ports import NativeParser
from web_access.domain.content import ContentObject


class InlineNativeParserExecutor:
    async def execute(
        self,
        parser: NativeParser,
        source: ContentObject,
        inspection: ContentInspection,
        data: bytes,
    ) -> NativeParserOutput:
        return await parser.parse(source, inspection, data)
