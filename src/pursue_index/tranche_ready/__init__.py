"""The machine-readable tranche-ready record the poll publishes (R7C.31).

On a confirmed upstream change the credential-free snapshot job writes
``data/tranche-ready/<sha12>.json``: one record per tranche CSV sha, shaped
by the schema pursue-opsec owns (vendored byte-for-byte at
``schemas/tranche-ready.schema.json``). Modules:

* ``schema``     -- a dependency-free validator for that schema document;
* ``old_bytes``  -- the credential-free old-side PDF fetch, checked against
  the asset-bytes registry, and the content-addressed bytes dir;
* ``candidates`` -- one rename/quarantine candidate per diff row, with its
  byte verdict;
* ``estimate``   -- the record's ``estimate`` block, priced by
  ``release/rates.py``;
* ``record``     -- the whole record;
* ``writer``     -- validate-before-write, append-only per sha.

Everything here is pure or takes its I/O as an argument, so the poll lane
(``requirements-poll.txt`` only) can run it and tests can stub the network.
"""
