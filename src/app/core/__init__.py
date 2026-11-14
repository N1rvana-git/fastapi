"""Cross-cutting infrastructure (config, db, redis, logging, errors, middleware).

Nothing in this package may import a domain module: it is the bottom of the
dependency graph. Business rules live in ``src.app.modules``.
"""
