from graphql.contrib.asyncio_py35.core import graphql
from graphql.core.type import (
    GraphQLSchema,
    GraphQLObjectType,
    GraphQLField,
    GraphQLString
)
import functools
import asyncio


def run_until_complete(fun):
    @functools.wraps(fun)
    def wrapper(*args, **kwargs):
        coro = fun(*args, **kwargs)
        return asyncio.get_event_loop().run_until_complete(coro)
    return wrapper


@run_until_complete
async def test_asyncio_py35_executor():
    doc = 'query Example { a }'

    async def resolver(context, *_):
        await asyncio.sleep(0.001)
        return 'hey'

    Type = GraphQLObjectType('Type', {
        'a': GraphQLField(GraphQLString, resolver=resolver)
    })

    result = await graphql(GraphQLSchema(Type), doc)
    assert not result.errors
    assert result.data == {'a': 'hey'}
