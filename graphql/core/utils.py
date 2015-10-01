from .language import ast
from .type.definition import (
    GraphQLEnumType,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLUnionType,
    get_named_type,
    get_nullable_type,
    is_composite_type,
)
from .type.introspection import SchemaMetaFieldDef, TypeMetaFieldDef, TypeNameMetaFieldDef


def type_from_ast(schema, input_type_ast):
    if isinstance(input_type_ast, ast.ListType):
        inner_type = type_from_ast(schema, input_type_ast.type)
        if inner_type:
            return GraphQLList(inner_type)
        else:
            return None
    if isinstance(input_type_ast, ast.NonNullType):
        inner_type = type_from_ast(schema, input_type_ast.type)
        if inner_type:
            return GraphQLNonNull(inner_type)
        else:
            return None
    assert isinstance(input_type_ast, ast.NamedType), 'Must be a type name.'
    return schema.get_type(input_type_ast.name.value)


def pop(lst):
    if lst:
        lst.pop()


class TypeInfo(object):
    def __init__(self, schema):
        self._schema = schema
        self._type_stack = []
        self._parent_type_stack = []
        self._input_type_stack = []
        self._field_def_stack = []
        self._directive = None
        self._argument = None

    def get_type(self):
        if self._type_stack:
            return self._type_stack[-1]

    def get_parent_type(self):
        if self._parent_type_stack:
            return self._parent_type_stack[-1]

    def get_input_type(self):
        if self._input_type_stack:
            return self._input_type_stack[-1]

    def get_field_def(self):
        if self._field_def_stack:
            return self._field_def_stack[-1]

    def get_directive(self):
        return self._directive

    def get_argument(self):
        return self._argument

    def enter(self, node):
        schema = self._schema
        type = None
        if isinstance(node, ast.SelectionSet):
            named_type = get_named_type(self.get_type())
            composite_type = None
            if is_composite_type(named_type):
                composite_type = named_type
            self._parent_type_stack.append(composite_type)
        elif isinstance(node, ast.Field):
            parent_type = self.get_parent_type()
            field_def = None
            if parent_type:
                field_def = get_field_def(schema, parent_type, node)
            self._field_def_stack.append(field_def)
            self._type_stack.append(field_def and field_def.type)
        elif isinstance(node, ast.Directive):
            self._directive = schema.get_directive(node.name.value)
        elif isinstance(node, ast.OperationDefinition):
            if node.operation == 'query':
                type = schema.get_query_type()
            elif node.operation == 'mutation':
                type = schema.get_mutation_type()
            self._type_stack.append(type)
        elif isinstance(node, (ast.InlineFragment, ast.FragmentDefinition)):
            type = type_from_ast(schema, node.type_condition)
            self._type_stack.append(type)
        elif isinstance(node, ast.VariableDefinition):
            self._input_type_stack.append(type_from_ast(schema, node.type))
        elif isinstance(node, ast.Argument):
            arg_def = None
            arg_type = None
            field_or_directive = self.get_directive() or self.get_field_def()
            if field_or_directive:
                arg_def = [arg for arg in field_or_directive.args if arg.name == node.name.value]
                if arg_def:
                    arg_def = arg_def[0]
                    arg_type = arg_def.type
                else:
                    arg_def = None
            self._argument = arg_def
            self._input_type_stack.append(arg_type)
        elif isinstance(node, ast.ListValue):
            list_type = get_nullable_type(self.get_input_type())
            self._input_type_stack.append(
                list_type.of_type if isinstance(list_type, GraphQLList) else None
            )
        elif isinstance(node, ast.ObjectField):
            object_type = get_named_type(self.get_input_type())
            field_type = None
            if isinstance(object_type, GraphQLInputObjectType):
                input_field = object_type.get_fields().get(node.name.value)
                field_type = input_field.type if input_field else None
            self._input_type_stack.append(field_type)

    def leave(self, node):
        if isinstance(node, ast.SelectionSet):
            pop(self._parent_type_stack)
        elif isinstance(node, ast.Field):
            pop(self._field_def_stack)
            pop(self._type_stack)
        elif isinstance(node, ast.Directive):
            self._directive = None
        elif isinstance(node, (
                ast.OperationDefinition,
                ast.InlineFragment,
                ast.FragmentDefinition,
        )):
            pop(self._type_stack)
        elif isinstance(node, ast.VariableDefinition):
            pop(self._input_type_stack)
        elif isinstance(node, ast.Argument):
            self._argument = None
            pop(self._input_type_stack)
        elif isinstance(node, (ast.ListType, ast.ObjectField)):
            pop(self._input_type_stack)


def get_field_def(schema, parent_type, field_ast):
    """Not exactly the same as the executor's definition of get_field_def, in this
    statically evaluated environment we do not always have an Object type,
    and need to handle Interface and Union types."""
    name = field_ast.name.value
    if name == SchemaMetaFieldDef.name and schema.get_query_type() == parent_type:
        return SchemaMetaFieldDef
    elif name == TypeMetaFieldDef.name and schema.get_query_type() == parent_type:
        return TypeMetaFieldDef
    elif name == TypeNameMetaFieldDef.name and \
            isinstance(parent_type, (
                GraphQLObjectType,
                GraphQLInterfaceType,
                GraphQLUnionType,
            )):
        return TypeNameMetaFieldDef
    elif isinstance(parent_type, (GraphQLObjectType, GraphQLInterfaceType)):
        return parent_type.get_fields().get(name)


def is_valid_literal_value(type, value_ast):
    if isinstance(type, GraphQLNonNull):
        if not value_ast:
            return False

        of_type = type.of_type
        return is_valid_literal_value(of_type, value_ast)

    if not value_ast:
        return True

    if isinstance(value_ast, ast.Variable):
        return True

    if isinstance(type, GraphQLList):
        item_type = type.of_type
        if isinstance(value_ast, ast.ListValue):
            return all(is_valid_literal_value(item_type, item_ast) for item_ast in value_ast.values)

        return is_valid_literal_value(item_type, value_ast)

    if isinstance(type, GraphQLInputObjectType):
        if not isinstance(value_ast, ast.ObjectValue):
            return False

        fields = type.get_fields()
        field_asts = value_ast.fields

        if any(not fields.get(field_ast.name.value, None) for field_ast in field_asts):
            return False

        field_ast_map = {field_ast.name.value: field_ast for field_ast in field_asts}
        get_field_ast_value = lambda field_name: field_ast_map[
            field_name].value if field_name in field_ast_map else None

        return all(is_valid_literal_value(field.type, get_field_ast_value(field_name))
                   for field_name, field in fields.items())

    assert isinstance(type, (GraphQLScalarType, GraphQLEnumType)), 'Must be input type'

    return type.parse_literal(value_ast) is not None
