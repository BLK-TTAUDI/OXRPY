"""Empty at runtime. Editors and type checkers read ``_signatures.pyi`` instead, which lists
the real return types of the methods both clients share. See scripts/gen_signatures.py."""


class SyncSignatures:
    pass


class AsyncSignatures:
    pass
