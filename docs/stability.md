# Stability policy

aiogzip `2.0.0b1` is the first 2.0 beta. Beginning with that release, the
documented public API is frozen for the 2.0 line: no intentional incompatible
change is planned before 2.0 stable. Later betas and release candidates may
contain compatible correctness fixes, documentation and packaging updates,
and semantics-preserving performance improvements.

Beta is still a prerelease. Test it against your workloads and pin an exact
version or an appropriate prerelease range until 2.0 stable is available.

## Public API

The canonical public import paths are the top-level `aiogzip` package and the
`aiogzip.codec` module. The names documented in the [API reference](api.md),
including the top-level `__all__` and `aiogzip.codec.__all__` inventories, are
the supported 2.0 surface. The high-level asyncio APIs and the synchronous
codec receive the same beta compatibility commitment.

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

## Examples and future changes

Repository examples are maintained and tested as integration workflows, but
their helper functions, command-line wording, frame formats, staging layouts,
and status labels are application code rather than package API. Only the
public aiogzip names they import receive the compatibility guarantee above.

After 2.0 stable, an unavoidable incompatible change to public API would be
announced in the changelog and migration documentation and would normally use
a deprecation period before removal. Security or correctness constraints may
occasionally require a faster response, which would be documented explicitly.

Report suspected compatibility regressions through the project's
[issue tracker](https://github.com/geoff-davis/aiogzip/issues). Report security
problems privately as described in the
[security policy](https://github.com/geoff-davis/aiogzip/security/policy).
