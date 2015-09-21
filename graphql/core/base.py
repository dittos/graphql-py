"""Common base utilities for other implementations"""

from .language.source import Source
from .language.parser import parse
from .validation import validate


def parse_request_and_validate(schema, request, source_name='Graphql request'):
    source = Source(request, source_name)
    ast = parse(source)
    validation_errors = validate(schema, ast)
    return ast, validation_errors
