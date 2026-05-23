from __future__ import annotations

from backend.documents_getter_endpoints.router import _apply_pagination


class FakeQuery:
    def __init__(self):
        self.range_args = None

    def range(self, start, end):
        self.range_args = (start, end)
        return self


def test_apply_pagination_uses_supabase_inclusive_range():
    query = FakeQuery()

    returned = _apply_pagination(query, limit=25, offset=50)

    assert returned is query
    assert query.range_args == (50, 74)


def test_apply_pagination_keeps_query_when_no_limit_or_offset():
    query = FakeQuery()

    returned = _apply_pagination(query, limit=None, offset=None)

    assert returned is query
    assert query.range_args is None
