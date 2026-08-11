"""Single-pass bounded CSV parser with deterministic dialect handling."""

from __future__ import annotations

import csv
import io

from web_access.application.common.hints import Warning
from web_access.application.content.models import (
    ContentInspection,
    NativeParserOutput,
    ParsedRepresentation,
    ParserDescriptor,
)
from web_access.core.config import ParserSettings
from web_access.domain.content import (
    ContentFormat,
    ContentObject,
    ContentRepresentationKind,
)
from web_access.infrastructure.content.parsers.common import (
    NativeParserError,
    bounded_json_bytes,
    require_input_bound,
)


class CsvNativeParser:
    def __init__(self, settings: ParserSettings) -> None:
        self._settings = settings

    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            capability="csv",
            revision="csv-stdlib-v1",
            profile_revision="csv-default-v1",
            supported_formats=(ContentFormat.CSV,),
            primary_representation=ContentRepresentationKind.STRUCTURED,
            representation_schema_revision="content-csv-v1",
        )

    async def parse(
        self, source: ContentObject, inspection: ContentInspection, data: bytes
    ) -> NativeParserOutput:
        del source
        require_input_bound(data, self._settings.inline_max_input_bytes)
        try:
            text = data.decode(inspection.encoding or "utf-8-sig")
        except (LookupError, UnicodeDecodeError) as error:
            raise NativeParserError("unable to decode CSV Content") from error
        sample = text[: self._settings.csv_sample_chars]
        warning: tuple[Warning, ...] = ()
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
            warning = (
                Warning(
                    code="csv_dialect_ambiguous",
                    message="CSV dialect was ambiguous; the bounded comma profile was used.",
                ),
            )
        rows: list[list[str]] = []
        truncated = False
        try:
            for index, row in enumerate(csv.reader(io.StringIO(text), dialect=dialect)):
                if index >= self._settings.csv_max_rows:
                    truncated = True
                    break
                if len(row) > self._settings.csv_max_columns:
                    raise NativeParserError("CSV exceeds column limit")
                if any(len(cell) > self._settings.csv_max_cell_chars for cell in row):
                    raise NativeParserError("CSV exceeds cell character limit")
                rows.append(row)
        except csv.Error as error:
            raise NativeParserError("invalid CSV Content") from error
        encoded = bounded_json_bytes(
            {
                "schema_revision": "content-csv-v1",
                "delimiter": dialect.delimiter,
                "rows": rows,
                "truncated": truncated,
            },
            self._settings.inline_max_output_bytes,
        )
        return NativeParserOutput(
            representations=(
                ParsedRepresentation(
                    representation=ContentRepresentationKind.STRUCTURED,
                    media_type="application/vnd.web-access.content+json",
                    schema_revision="content-csv-v1",
                    data=encoded,
                ),
            ),
            warnings=warning,
        )
