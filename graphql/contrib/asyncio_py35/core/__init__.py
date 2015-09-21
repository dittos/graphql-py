from graphql.core.execution.base import ExecutionResult
from graphql.core.base import parse_request_and_validate
from .execution import execute


async def graphql(schema, request='', root=None, vars=None, operation_name=None):
    ast, validation_errors = parse_request_and_validate(schema, request)
    if validation_errors:
        return ExecutionResult(
            data=None,
            errors=validation_errors,
        )
    return await execute(
        schema,
        root or object(),
        ast,
        operation_name,
        vars or {},
    )