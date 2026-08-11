"""Registered bounded native Content parsers."""

from web_access.infrastructure.content.parsers.csv_parser import CsvNativeParser
from web_access.infrastructure.content.parsers.executor import InlineNativeParserExecutor
from web_access.infrastructure.content.parsers.json_parser import JsonNativeParser
from web_access.infrastructure.content.parsers.registry import ContentNativeParserRegistry
from web_access.infrastructure.content.parsers.text_parser import TextNativeParser
from web_access.infrastructure.content.parsers.xml_parser import XmlNativeParser

__all__ = [
    "ContentNativeParserRegistry",
    "CsvNativeParser",
    "InlineNativeParserExecutor",
    "JsonNativeParser",
    "TextNativeParser",
    "XmlNativeParser",
]
