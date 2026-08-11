"""PDF capability marker; execution is permitted only through the isolated router."""

from web_access.application.content.models import (
    ContentInspection,
    NativeParserOutput,
    ParserDescriptor,
)
from web_access.domain.content import (
    ContentFormat,
    ContentObject,
    ContentRepresentationKind,
    ParserExecutionMode,
)
from web_access.infrastructure.content.parsers.common import NativeParserError


class PdfNativeParser:
    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            capability="pdf",
            revision="pdf-pypdf-isolated-v1",
            profile_revision="pdf-native-text-v1",
            supported_formats=(ContentFormat.PDF,),
            primary_representation=ContentRepresentationKind.TEXT,
            representation_schema_revision="content-pdf-text-v1",
            execution_mode=ParserExecutionMode.ISOLATED,
        )

    async def parse(
        self, source: ContentObject, inspection: ContentInspection, data: bytes
    ) -> NativeParserOutput:
        del source, inspection, data
        raise NativeParserError("PDF parsing requires the isolated parser executor")
