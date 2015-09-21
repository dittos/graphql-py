from pytest import raises
from graphql.core.language.error import LanguageError
from graphql.core.language.source import Source
from graphql.core.language.parser import parse, Loc
from graphql.core.language import ast
from fixtures import KITCHEN_SINK


def test_parse_provides_useful_errors():
    with raises(LanguageError) as excinfo:
        parse("""{ ...MissingOn }
fragment MissingOn Type
""")
    assert 'Syntax Error GraphQL (2:20) Expected "on", found Name "Type"' in str(excinfo.value)

    with raises(LanguageError) as excinfo:
        parse('{ field: {} }')
    assert 'Syntax Error GraphQL (1:10) Expected Name, found {' in str(excinfo.value)

    with raises(LanguageError) as excinfo:
        parse('notanoperation Foo { field }')
    assert 'Syntax Error GraphQL (1:1) Unexpected Name "notanoperation"' in str(excinfo.value)

    with raises(LanguageError) as excinfo:
        parse('...')
    assert 'Syntax Error GraphQL (1:1) Unexpected ...' in str(excinfo.value)


def test_parse_provides_useful_error_when_using_source():
    with raises(LanguageError) as excinfo:
        parse(Source('query', 'MyQuery.graphql'))
    assert 'Syntax Error MyQuery.graphql (1:6) Expected Name, found EOF' in str(excinfo.value)


def test_parses_variable_inline_values():
    parse('{ field(complex: { a: { b: [ $var ] } }) }')


def test_parses_constant_default_values():
    with raises(LanguageError) as excinfo:
        parse('query Foo($x: Complex = { a: { b: [ $var ] } }) { field }')
    assert 'Syntax Error GraphQL (1:37) Unexpected $' in str(excinfo.value)


def test_duplicate_keys_in_input_object_is_syntax_error():
    with raises(LanguageError) as excinfo:
        parse('{ field(arg: { a: 1, a: 2 }) }')
    assert 'Syntax Error GraphQL (1:22) Duplicate input object field a.' in str(excinfo.value)


def test_parses_kitchen_sink():
    parse(KITCHEN_SINK)


def test_format_loc():
    assert repr(Loc(5, 3)) == '<Loc start=5 end=3>'
    assert repr(Loc(5, 3, 2)) == '<Loc start=5 end=3 source=2>'


def test_parse_creates_ast():
    source = Source("""{
  node(id: 4) {
    id,
    name
  }
}
""")
    result = parse(source)

    assert result == \
           ast.Document(
               loc=Loc(0, 41, source),
               definitions=
               [ast.OperationDefinition(
                   loc=Loc(0, 40, source),
                   operation='query',
                   name=None,
                   variable_definitions=None,
                   directives=[],
                   selection_set=ast.SelectionSet(
                       loc=Loc(0, 40, source),
                       selections=
                       [ast.Field(
                           loc=Loc(4, 38, source),
                           alias=None,
                           name=ast.Name(
                               loc=Loc(4, 8, source),
                               value='node'),
                           arguments=[ast.Argument(
                               name=ast.Name(loc=Loc(9, 11, source),
                                             value='id'),
                               value=ast.IntValue(
                                   loc=Loc(13, 14, source),
                                   value='4'),
                               loc=Loc(9, 14, source))],
                           directives=[],
                           selection_set=ast.SelectionSet(
                               loc=Loc(16, 38, source),
                               selections=
                               [ast.Field(
                                   loc=Loc(22, 24, source),
                                   alias=None,
                                   name=ast.Name(
                                       loc=Loc(22, 24, source),
                                       value='id'),
                                   arguments=[],
                                   directives=[],
                                   selection_set=None),
                                   ast.Field(
                                       loc=Loc(30, 34, source),
                                       alias=None,
                                       name=ast.Name(
                                           loc=Loc(30, 34, source),
                                           value='name'),
                                       arguments=[],
                                       directives=[],
                                       selection_set=None)]))]))])
