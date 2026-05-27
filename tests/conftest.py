import os

# Tests run without real Postgres unless Testcontainers provides URLs.
os.environ.setdefault("REQUIRE_DBS", "0")
