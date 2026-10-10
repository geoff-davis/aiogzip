# Stability policy

aiogzip 2.0 is a stable release line. Its documented public API, defined
below, has been frozen since `2.0.0b1`, and aiogzip follows
[semantic versioning](https://semver.org/) for that API from 2.0.0 on.

## Versioning

- A **patch release** (2.0.x) contains compatible correctness and security
  fixes, documentation and packaging updates, and performance improvements
  that preserve semantics. It adds no public names.
- A **minor release** (2.x.0) may also add public names and parameters,
  deprecate public API, and change the supported Python versions as
  described below. Existing code that uses the public API as documented
  keeps working.
- An incompatible change to the public API, including removing a deprecated
  name, is made only in a new major release.

## Deprecation

Public API is deprecated before it is removed. A deprecation is announced in
the changelog and the migration documentation and, where the runtime can
detect the use, emits `DeprecationWarning`. A deprecated name remains
available for at least one minor release, and is removed no earlier than the
next major release.

Security or correctness constraints may occasionally require a faster
response, such as rejecting input that was previously accepted. Such a change
is documented explicitly in the changelog.

## Python versions

aiogzip 2.0 supports Python 3.11 through 3.15. A new CPython version is
supported once it is released and the test matrix covers it, which can happen
in a patch or minor release. Support for a CPython version that has reached
end of life may be dropped in a minor release, never in a patch release, and
the package metadata (`requires-python`) changes with it so that installers
keep selecting the last compatible release.

## Public API

The canonical public import paths are the top-level `aiogzip` package and the
`aiogzip.codec` module. The names documented in the [API reference](api.md),
including the top-level `__all__` and `aiogzip.codec.__all__` inventories, are
the supported 2.0 surface. The high-level asyncio APIs and the synchronous
codec receive the same compatibility commitment.

Modules and names beginning with an underscore are private unless a name is
also re-exported through a documented public path. In particular,
`aiogzip._common`, `aiogzip._binary`, `aiogzip._text`,
`aiogzip._inspection`, and `aiogzip._streaming` may change without notice.
Private caches, progress events, engine adapters, and scheduling details are
not compatibility promises.

## What the freeze covers

- Public function and method signatures, including their defaults and
  overload behavior, are frozen. Conventional binary and text mode literals
  continue to narrow to their respective file classes, while dynamic mode
  strings return the documented union.
- Public exception types and inheritance are frozen. Only message prefixes
  explicitly identified as stable are covered; currently that is
  `decompressed output exceeded max_decompressed_size`. Complete messages
  containing offsets, sizes, member numbers, engine names, or platform text
  may change.
- Public dataclass names, field order, field names, defaults, annotations, and
  documented frozen/slots behavior are frozen. Incidental generated `repr()`
  formatting is not.
- The member sets and runtime-checkable status of the public `WithAsync*`
  protocols are part of the typing contract. `CodecOperation` retains its
  iterable and deterministic `close()` shape. `ZlibEngine` remains a typing
  alias, currently represented by `Any`, rather than a runtime engine object.
- Documented `GZIP_*` constant names and numeric values are frozen for 2.0.
- Lifecycle, ownership, output-bound, integrity-validation, and cancellation
  behavior described in the user guides is part of the public contract.

The availability and field shape of `EngineInfo` and the availability of
`engine_info()` are public. Their human-readable engine-name strings are
diagnostics, not stable feature flags; do not branch on an exact string. The
literal value of `aiogzip.__version__` likewise changes with each release,
though it remains a public string synchronized with package metadata.

## Supported release lines

The 2.0 line receives correctness and security fixes. The 1.x line, which
still serves Python 3.8 through 3.10, receives security fixes only, until
2027-04-30; after that date it receives no further releases. Python 3.10, the
last of those interpreters, reached end of life on 2026-10-01. Fixes made in
2.0 are not backported to 1.x unless they are security fixes. See the
[security policy](https://github.com/geoff-davis/aiogzip/security/policy) for
how to report a vulnerability.

## Examples and reporting

Repository examples are maintained and tested as integration workflows, but
their helper functions, command-line wording, frame formats, staging layouts,
and status labels are application code rather than package API. Only the
public aiogzip names they import receive the compatibility guarantee above.

Report suspected compatibility regressions through the project's
[issue tracker](https://github.com/geoff-davis/aiogzip/issues). Report security
problems privately as described in the
[security policy](https://github.com/geoff-davis/aiogzip/security/policy).
