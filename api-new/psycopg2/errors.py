"""Subset of psycopg2 error classes used for exception matching."""


class UniqueViolation(Exception):  # noqa: N818
    pass


class UndefinedTable(Exception):  # noqa: N818
    pass
