"""The board: architecture.md §7's projection + command inbox, authoritative for nothing.

`projection.py` (git -> board, read-only mirror) and `inbox.py` (board -> git, an append-only
command stream) are two directions through the same `BoardAdapter`. Neither reads the other's
side to decide anything -- see each module's own docstring.
"""
