from graphql.core import Source


def test_source_eq():
    s1 = Source('foo', 'bar')
    s2 = Source('foo', 'bar')

    assert s1 == s2

    s3 = Source('bar', 'baz')
    assert s1 != s3

    s4 = 'not a source'
    assert s1 != s4
