# -*- coding: utf-8 -*-
import inspect

from graphql.core.type.definition import GraphQLNonNull
from graphql.core.execution.base import (
    execute_gen,
    collect_type_and_fields,
    execute_fields_serially_gen,
    resolve_field_gen,
    complete_value_gen
)


async def execute(schema, root, ast, operation_name='', args=None):
    """Implements the "Evaluating requests" section of the spec."""
    executor = execute_gen(schema, root, ast, operation_name=operation_name, args=args)
    data = await execute_operation(*next(executor))
    return executor.send(data)


async def execute_operation(ctx, root, operation):
    """Implements the "Evaluating operations" section of the spec."""
    type, fields = collect_type_and_fields(ctx, root, operation)
    if operation.operation == 'mutation':
        return await execute_fields_serially(ctx, type, root, fields)
    return await execute_fields(ctx, type, root, fields)


async def execute_fields_serially(ctx, parent_type, source, fields):
    """Implements the "Evaluating selection sets" section of the spec
    for "write" mode."""
    executor = execute_fields_serially_gen(ctx, parent_type, source, fields)
    try:
        args = next(executor)
        while True:
            result = await resolve_field(*args)
            args = executor.send(result)
    except StopIteration as exc:
        return exc.args[0]


async def execute_fields(ctx, parent_type, source, fields):
    """Implements the "Evaluating selection sets" section of the spec
    for "read" mode."""
    # FIXME: just fallback to serial execution for now.
    return await execute_fields_serially(ctx, parent_type, source, fields)


async def resolve_field(ctx, parent_type, source, field_asts):
    """A wrapper function for resolving the field, that catches the error
    and adds it to the context's global if the error is not rethrowable."""

    resolver = resolve_field_gen(ctx, parent_type, source, field_asts)
    fn, *fn_args = next(resolver)
    if inspect.iscoroutinefunction(fn):
        result = await fn(*fn_args)
    else:
        result = fn(*fn_args)
    ctx, return_type, field_asts, info, result = resolver.send(result)
    return await complete_value_catching_error(ctx, return_type, field_asts, info, result)


async def complete_value_catching_error(ctx, return_type, field_asts, info, result):
    try:
        return await complete_value(ctx, return_type, field_asts, info, result)
    except Exception as e:
        # If the field type is non-nullable, then it is resolved without any
        # protection from errors.
        if isinstance(return_type, GraphQLNonNull):
            raise
        # Otherwise, error protection is applied, logging the error and
        # resolving a null value for this field if one is encountered.
        ctx.errors.append(e)
        return None


async def complete_value(ctx, return_type, field_asts, info, result):
    completer = complete_value_gen(ctx, return_type, field_asts, info, result)
    try:
        what, args = next(completer)
        while True:
            if what == 'complete_value_catching_error':
                result = await complete_value_catching_error(*args)
            elif what == 'execute_fields':
                result = await execute_fields(*args)
            elif what == 'complete_value':
                result = await complete_value(*args)
            else:
                assert False, 'bad "what" {} coming from complete_value_gen'.format(what)
            what, args = completer.send(result)
    except StopIteration as exc:
        return exc.args and exc.args[0] or None
