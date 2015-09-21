# -*- coding: utf-8 -*-
from ..type.definition import GraphQLNonNull
from .base import (
    execute_gen,
    collect_type_and_fields,
    execute_fields_serially_gen,
    resolve_field_gen,
    complete_value_gen
)


def execute(schema, root, ast, operation_name='', args=None):
    """Implements the "Evaluating requests" section of the spec."""
    executor = execute_gen(schema, root, ast, operation_name=operation_name, args=args)
    execute_args = next(executor)
    data = execute_operation(*execute_args)
    return executor.send(data)


def execute_operation(ctx, root, operation):
    """Implements the "Evaluating operations" section of the spec."""
    type, fields = collect_type_and_fields(ctx, root, operation)
    if operation.operation == 'mutation':
        return execute_fields_serially(ctx, type, root, fields)
    return execute_fields(ctx, type, root, fields)


def execute_fields_serially(ctx, parent_type, source, fields):
    """Implements the "Evaluating selection sets" section of the spec
    for "write" mode."""
    executor = execute_fields_serially_gen(ctx, parent_type, source, fields)
    try:
        args = next(executor)
        while True:
            result = resolve_field(*args)
            args = executor.send(result)
    except StopIteration as exc:
        return exc.args and exc.args[0] or None


def execute_fields(ctx, parent_type, source, fields):
    """Implements the "Evaluating selection sets" section of the spec
    for "read" mode."""
    # FIXME: just fallback to serial execution for now.
    return execute_fields_serially(ctx, parent_type, source, fields)


def resolve_field(ctx, parent_type, source, field_asts):
    """A wrapper function for resolving the field, that catches the error
    and adds it to the context's global if the error is not rethrowable."""

    resolver = resolve_field_gen(ctx, parent_type, source, field_asts)
    fn, *fn_args = next(resolver)
    result = fn(*fn_args)
    ctx, return_type, field_asts, info, result = resolver.send(result)
    return complete_value_catching_error(ctx, return_type, field_asts, info, result)


def complete_value_catching_error(ctx, return_type, field_asts, info, result):
    try:
        return complete_value(ctx, return_type, field_asts, info, result)
    except Exception as e:
        # If the field type is non-nullable, then it is resolved without any
        # protection from errors.
        if isinstance(return_type, GraphQLNonNull):
            raise
        # Otherwise, error protection is applied, logging the error and
        # resolving a null value for this field if one is encountered.
        ctx.errors.append(e)
        return None


def complete_value(ctx, return_type, field_asts, info, result):
    completer = complete_value_gen(ctx, return_type, field_asts, info, result)
    try:
        what, args = next(completer)
        while True:
            if what == 'complete_value_catching_error':
                result = complete_value_catching_error(*args)
            elif what == 'execute_fields':
                result = execute_fields(*args)
            elif what == 'complete_value':
                result = complete_value(*args)
            else:
                assert False, 'bad "what" {} coming from complete_value_gen'.format(what)
            what, args = completer.send(result)
    except StopIteration as exc:
        return exc.args and exc.args[0] or None
