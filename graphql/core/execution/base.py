# -*- coding: utf-8 -*-
import collections
from ..error import GraphQLError, format_error
from ..utils import type_from_ast, is_nullish
from ..language import ast
from .values import get_variable_values, get_argument_values
from ..type.definition import (
    GraphQLScalarType,
    GraphQLObjectType,
    GraphQLInterfaceType,
    GraphQLUnionType,
    GraphQLEnumType,
    GraphQLList,
    GraphQLNonNull,
)
from ..type.introspection import (
    SchemaMetaFieldDef,
    TypeMetaFieldDef,
    TypeNameMetaFieldDef,
)
from ..type.directives import (
    GraphQLIncludeDirective,
    GraphQLSkipDirective,
)

Undefined = object()


"""
Terminology

"Definitions" are the generic name for top-level statements in the document.
Examples of this include:
1) Operations (such as a query)
2) Fragments

"Operations" are a generic name for requests in the document.
Examples of this include:
1) query,
2) mutation

"Selections" are the statements that can appear legally and at
single level of the query. These include:
1) field references e.g "a"
2) fragment "spreads" e.g. "...c"
3) inline fragment "spreads" e.g. "...on Type { a }"
"""


class ExecutionContext(object):
    """Data that must be available at all points during query execution.

    Namely, schema of the type system that is currently executing,
    and the fragments defined in the query document"""
    def __init__(self, schema, root, document_ast, operation_name, args):
        """Constructs a ExecutionContext object from the arguments passed
        to execute, which we will pass throughout the other execution
        methods."""
        errors = []
        operations = {}
        fragments = {}
        for statement in document_ast.definitions:
            if isinstance(statement, ast.OperationDefinition):
                name = ''
                if statement.name:
                    name = statement.name.value
                operations[name] = statement
            elif isinstance(statement, ast.FragmentDefinition):
                fragments[statement.name.value] = statement
        if not operation_name and len(operations) != 1:
            raise GraphQLError(
                'Must provide operation name '
                'if query contains multiple operations')
        op_name = operation_name or next(iter(operations.keys()))
        operation = operations.get(op_name)
        if not operation:
            raise GraphQLError('Unknown operation name: {}'.format(op_name))
        variables = get_variable_values(schema, operation.variable_definitions or [], args)

        self.schema = schema
        self.fragments = fragments
        self.root = root
        self.operation = operation
        self.variables = variables
        self.errors = errors


class ExecutionResult(object):
    """The result of execution. `data` is the result of executing the
    query, `errors` is null if no errors occurred, and is a
    non-empty array if an error occurred."""

    def __init__(self, data, errors=None):
        self.data = data
        self.errors = errors


def get_operation_root_type(schema, operation):
    op = operation.operation
    if op == 'query':
        return schema.get_query_type()
    elif op == 'mutation':
        mutation_type = schema.get_mutation_type()
        if not mutation_type:
            raise GraphQLError(
                'Schema is not configured for mutations',
                [operation]
            )
        return mutation_type
    raise GraphQLError(
        'Can only execute queries and mutations',
        [operation]
    )


def collect_fields(ctx, type, selection_set, fields, prev_fragment_names):
    for selection in selection_set.selections:
        directives = selection.directives
        if isinstance(selection, ast.Field):
            if not should_include_node(ctx, directives):
                continue
            name = get_field_entry_key(selection)
            if name not in fields:
                fields[name] = []
            fields[name].append(selection)
        elif isinstance(selection, ast.InlineFragment):
            if not should_include_node(ctx, directives) or \
                    not does_fragment_condition_match(ctx, selection, type):
                continue
            collect_fields(
                ctx, type, selection.selection_set,
                fields, prev_fragment_names)
        elif isinstance(selection, ast.FragmentSpread):
            frag_name = selection.name.value
            if frag_name in prev_fragment_names or \
                    not should_include_node(ctx, directives):
                continue
            prev_fragment_names.add(frag_name)
            fragment = ctx.fragments.get(frag_name)
            frag_directives = fragment.directives
            if not fragment or \
                    not should_include_node(ctx, frag_directives) or \
                    not does_fragment_condition_match(ctx, fragment, type):
                continue
            collect_fields(
                ctx, type, fragment.selection_set,
                fields, prev_fragment_names)
    return fields


def should_include_node(ctx, directives):
    """Determines if a field should be included based on the @include and
    @skip directives, where @skip has higher precidence than @include."""
    if directives:
        skip_ast = None
        for directive in directives:
            if directive.name.value == GraphQLSkipDirective.name:
                skip_ast = directive
                break
        if skip_ast:
            args = get_argument_values(
                GraphQLSkipDirective.args,
                skip_ast.arguments,
                ctx.variables,
            )
            return not args.get('if')

        include_ast = None
        for directive in directives:
            if directive.name.value == GraphQLIncludeDirective.name:
                include_ast = directive
                break
        if include_ast:
            args = get_argument_values(
                GraphQLIncludeDirective.args,
                include_ast.arguments,
                ctx.variables,
            )
            return bool(args.get('if'))

    return True


def does_fragment_condition_match(ctx, fragment, type_):
    conditional_type = type_from_ast(ctx.schema, fragment.type_condition)
    if type(conditional_type) == type(type_):
        return True
    if isinstance(conditional_type, (GraphQLInterfaceType, GraphQLUnionType)):
        return conditional_type.is_possible_type(type_)
    return False


def get_field_entry_key(node):
    """Implements the logic to compute the key of a given field’s entry"""
    if node.alias:
        return node.alias.value
    return node.name.value


class ResolveInfo(object):
    def __init__(self, field_name, field_asts, return_type, parent_type, context):
        self.field_name = field_name
        self.field_ast = field_asts
        self.return_type = return_type
        self.parent_type = parent_type
        self.context = context

    @property
    def schema(self):
        return self.context.schema

    @property
    def fragments(self):
        return self.context.fragments

    @property
    def root_value(self):
        return self.context.root_value

    @property
    def operation(self):
        return self.context.operation

    @property
    def variable_values(self):
        return self.context.variables


def complete_value_gen(ctx, return_type, field_asts, info, result):
    """Implements the instructions for completeValue as defined in the
    "Field entries" section of the spec.

    If the field type is Non-Null, then this recursively completes the value for the inner type. It throws a field error
    if that completion returns null, as per the "Nullability" section of the spec.

    If the field type is a List, then this recursively completes the value for the inner type on each item in the list.

    If the field type is a Scalar or Enum, ensures the completed value is a legal value of the type by calling the `serialize`
    method of GraphQL type definition.

    Otherwise, the field type expects a sub-selection set, and will complete the value by evaluating all sub-selections."""
    # If field type is NonNull, complete for inner type, and throw field error if result is null.
    if isinstance(return_type, GraphQLNonNull):
        completed = yield 'complete_value', (ctx, return_type.of_type, field_asts, info, result)
        if completed is None:
            raise GraphQLError(
                'Cannot return null for non-nullable type.',
                field_asts
            )
        return completed

    # If result is null-like, return null.
    if is_nullish(result):
        return None

    # If field type is List, complete each item in the list with the inner type
    if isinstance(return_type, GraphQLList):
        assert isinstance(result, collections.Iterable), \
            'User Error: expected iterable, but did not find one.'

        item_type = return_type.of_type
        retval = []
        for item in result:
            retval.append((yield 'complete_value_catching_error', (ctx, item_type, field_asts, info, item)))
        return retval

    # If field type is Scalar or Enum, serialize to a valid value, returning null if coercion is not possible.
    if isinstance(return_type, (GraphQLScalarType, GraphQLEnumType)):
        serialized_result = return_type.serialize(result)
        if is_nullish(serialized_result):
            return None
        return serialized_result

    # Field type must be Object, Interface or Union and expect sub-selections.
    if isinstance(return_type, GraphQLObjectType):
        object_type = return_type
    elif isinstance(return_type, (GraphQLInterfaceType, GraphQLUnionType)):
        object_type = return_type.resolve_type(result)
    else:
        object_type = None

    if not object_type:
        return None

    # Collect sub-fields to execute to complete this value.
    subfield_asts = {}
    visited_fragment_names = set()
    for field_ast in field_asts:
        selection_set = field_ast.selection_set
        if selection_set:
            subfield_asts = collect_fields(
                ctx, object_type, selection_set,
                subfield_asts, visited_fragment_names)

    return (yield 'execute_fields', (ctx, object_type, result, subfield_asts))


def default_resolve_fn(source, args, info):
    """If a resolve function is not given, then a default resolve behavior is used which takes the property of the source object
    of the same name as the field and returns it as the result, or if it's a function, returns the result of calling that function."""
    name = info.field_name
    property = getattr(source, name, None)
    if callable(property):
        return property()
    return property


def get_field_def(schema, parent_type, field_name):
    """This method looks up the field on the given type defintion.
    It has special casing for the two introspection fields, __schema
    and __typename. __typename is special because it can always be
    queried as a field, even in situations where no other fields
    are allowed, like on a Union. __schema could get automatically
    added to the query type, but that would require mutating type
    definitions, which would cause issues."""
    if field_name == SchemaMetaFieldDef.name and schema.get_query_type() == parent_type:
        return SchemaMetaFieldDef
    elif field_name == TypeMetaFieldDef.name and schema.get_query_type() == parent_type:
        return TypeMetaFieldDef
    elif field_name == TypeNameMetaFieldDef.name:
        return TypeNameMetaFieldDef
    return parent_type.get_fields().get(field_name)


def execute_gen(schema, root, ast, operation_name='', args=None):
    assert schema, 'Must provide schema'
    ctx = ExecutionContext(schema, root, ast, operation_name, args)
    try:
        data = yield ctx, root, ctx.operation
    except Exception as e:
        ctx.errors.append(e)
        data = None
    if not ctx.errors:
        yield ExecutionResult(data)
    formatted_errors = list(map(format_error, ctx.errors))
    yield ExecutionResult(data, formatted_errors)


def collect_type_and_fields(ctx, root, operation):
    """Implements the "Evaluating operations" section of the spec."""
    type = get_operation_root_type(ctx.schema, operation)
    fields = collect_fields(ctx, type, operation.selection_set, {}, set())
    return type, fields


def execute_fields_serially_gen(ctx, parent_type, source, fields):
    """Implements the "Evaluating selection sets" section of the spec
    for "write" mode."""
    results = {}
    for response_name, field_asts in fields.items():
        result = yield ctx, parent_type, source, field_asts
        if result is not Undefined:
            results[response_name] = result
    return results


def resolve_field_gen(ctx, parent_type, source, field_asts):
    """A wrapper function for resolving the field, that catches the error
    and adds it to the context's global if the error is not rethrowable."""
    field_ast = field_asts[0]
    field_name = field_ast.name.value

    field_def = get_field_def(ctx.schema, parent_type, field_name)
    if not field_def:
        return Undefined

    return_type = field_def.type
    resolve_fn = field_def.resolver or default_resolve_fn

    # Build a dict of arguments from the field.arguments AST, using the variables scope to fulfill any variable references.
    # TODO: find a way to memoize, in case this field is within a list type.
    args = get_argument_values(
        field_def.args, field_ast.arguments, ctx.variables
    )

    # The resolve function's optional third argument is a collection of
    # information about the current execution state.
    info = ResolveInfo(
        field_name,
        field_asts,
        return_type,
        parent_type,
        ctx
    )

    # If an error occurs while calling the field `resolve` function, ensure that it is wrapped as a GraphQLError with locations.
    # Log this error and return null if allowed, otherwise throw the error so the parent field can handle it.
    try:
        result = yield resolve_fn, source, args, info
    except Exception as e:
        reported_error = GraphQLError(str(e), [field_ast], e)
        if isinstance(return_type, GraphQLNonNull):
            raise reported_error
        ctx.errors.append(reported_error)
        return None

    yield ctx, return_type, field_asts, info, result
