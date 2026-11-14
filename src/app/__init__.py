"""Application package.

Layout follows a *modular monolith* (one deployable, strictly layered inside):

    src/app/
        main.py          # composition root: create_app() + lifespan
        core/            # cross-cutting infrastructure, no business rules
        shared/          # reusable dependencies/schemas shared by modules
        modules/<domain>/ # vertical slices: router -> service -> repository -> models
        api/router.py    # single place where routers are mounted

Dependency direction is one-way: modules -> core/shared, never the opposite.
"""

__all__ = ["__version__"]

__version__ = "0.2.0"
