"""BYU Badminton Club tournament management system.

Standard-library-only tournament engine: data import/validation, seeding,
bracket generation, scheduling, and a local web server for the admin tool and
public display. The `tournament` package holds pure logic with no UI or global
state; `tournament.server` and `tournament.cli` are the only entry points.
"""

__version__ = "0.1.0"
