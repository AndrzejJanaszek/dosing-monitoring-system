# Coding standards

The only place for the rules of writing code, tests and migrations in this repository. Other documents point here instead of repeating the rules. Git conventions are in [CONTRIBUTING.md](../CONTRIBUTING.md). Rules that a tool enforces are only named here; the configuration in `pyproject.toml` and `.importlinter` is the source of truth for them.

Each rule has a short statement, a one-sentence reason and a source (list at the end). Where code and this document disagree, this document wins and the code is fixed in a refactoring pull request.

## 1. Tools

`make check` must pass before a pull request: `ruff format --check`, `ruff check`, `mypy` (strict), `lint-imports`, `pytest`. CI runs the same command.

Ruff checks, besides the default `E` and `F`: `W`, `I`, `B`, `UP`, `SIM`, `RUF`, `PL`, and (from the refactoring that follows this document) `E501` line length, `N` PEP 8 naming, `FBT` boolean arguments, `SLF` private access, `PT` pytest style, `ARG` unused arguments and `BLE` blind `except`. The same refactoring lowers `line-length` from 100 to 99.

- **Formatting is ruff's.** Don't format by hand and don't argue about layout ruff decides. *Why:* one formatter removes style discussions from review. *Source:* [ruff], `pyproject.toml`.
- **Lines are at most 99 characters, strings included.** Split a long message into parts. *Why:* a longer line doesn't fit side by side in review. *Source:* [PEP8] §Maximum Line Length (79 by default; a team may agree on up to 99), `pyproject.toml`.
- **No suppressions in code.** No `# noqa`, `# type: ignore` or `cast()` to silence a tool; fix the code, or add an exception for a whole file in `pyproject.toml` with a reason in the pull request. *Why:* a suppression hides a problem from everyone after the author. *Source:* project decision; [mypy] `--warn-unused-ignores`.
- **mypy strict.** Every function has full annotations; no `Any` unless the value really is arbitrary (JSON from a log, a database row). *Why:* types are the documentation that cannot go out of date. *Source:* [mypy] `--strict`, [GSG] §2.21.

## 2. Comments, docstrings and layout

- **No comments and no docstrings.** The code is its own documentation through names, types and small functions; where it isn't, rewrite the code. Code written by AI has neither; a human may add a comment deliberately. *Why:* an outdated comment or docstring is worse than none, because people and AI tools trust it instead of reading the code. *Source:* project decisions (comments 2026-10-04, docstrings 2026-10-15).
- **Split function bodies into blocks with blank lines**: preparation, work, result; one step of a sequence per block. *Why:* without comments, blank lines are what shows the structure of a function. *Source:* [PEP8] §Blank Lines ("to indicate logical sections"), project decision.
- **Order inside a module:** imports, constants, type aliases, public classes and functions, private helpers. Inside a class: `__init__`, properties, public methods, private methods. *Why:* the reader finds the interface first and the details after it. *Source:* [PEP8] §Code Lay-out (imports and constants at the top); order of members: project convention.

## 3. Packages and modules

- **Layer packages:** `domain` (rules of the plant, no I/O, no clock), `messages` (values that cross threads), `acquisition` (ports, threads, the composition root), `persistence` (database), `config`, `logs`, `simulator` (development tool), later `api` and `ipc`. *Why:* the main architecture rules depend on these borders. *Source:* ADR-0004, ADR-0006.
- **Import borders are enforced by import-linter.** A new dependency between packages that breaks a contract needs an ADR change, not a contract change. *Source:* `.importlinter`, ADR-0006.
- **One module, one subject.** When a module passes about 300 lines, check whether it holds two subjects (for example a store and a thread that uses it). *Why:* a long module is read less carefully. *Source:* [GSG] §3.18 (the same idea for functions); limit: project convention.
- **Values shared by several packages live in the lowest package that needs them** (for example time units in a neutral module, not in `acquisition`). A package never repeats a constant or type of another one. *Why:* two copies of a rule drift apart. *Source:* project decision (one source of truth).
- **Absolute imports from `dms`** (`from dms.domain.events import ClosedEvent`); no relative imports (`from .events import ...`) and no wildcard imports. *Why:* the import line alone says where a name comes from. *Source:* [PEP8] §Imports ("absolute imports are recommended", "wildcard imports should be avoided").
- **No import cycles.** Don't hide a cycle behind `if TYPE_CHECKING:`; move the shared part to its own module. *Why:* a cycle means two modules are one subject split in the wrong place. *Source:* project convention.
- **`__init__.py` files stay empty and `__all__` is not used.** Import from the module that defines the name. *Source:* project convention.

## 4. Names

- **Case:** `snake_case` for modules, functions, variables; `CapWords` for classes and type aliases; `UPPER_CASE` for module constants. *Source:* [PEP8] §Naming Conventions.
- **Private with one underscore:** module helpers `_name`, attributes `self._name`. Start everything private and make public only what other modules use. Tests don't touch private names. *Why:* it is easy to make a name public later and hard to take it back. *Source:* [PEP8] §Designing for Inheritance.
- **No abbreviations and no one-letter names**, except `_` for an ignored value. `connection`, not `conn`; `tank_id`, not `id_` or `m`. *Why:* the user of this code reads English as a second language, and an abbreviation is one more thing to decode. *Source:* [GSG] §3.16.
- **Units in names** of every number with a unit: `_ns`, `_ms`, `_s`, `_kg`, `_hz`, `_c`. Clock readings: `wall_ns` (wall clock) and `mono_ns` (monotonic clock). *Why:* the unit is part of the meaning; a missing unit is a bug waiting to happen. *Source:* project convention, ADR-0004.
- **Functions are verbs** (`load_acquisition`, `close_crashed_events`); functions that return a bool read as a question (`is_compatible`). Event handlers of a class are `on_<what happened>`. *Source:* project convention.
- **Exceptions end in `Error`.** *Source:* [PEP8] §Exception Names, [PyTut] §8.6.

## 5. Types and data structures

- **Type aliases with `type`** (`type EventKind = ...`), generics with the new syntax (`def load[M: BaseModel](...)`). *Source:* [PEP695].
- **Values are frozen dataclasses:** `@dataclass(frozen=True, slots=True)`. Use `NamedTuple` only where tuple behaviour is needed (unpacking, ordering). *Why:* a value that cannot change can be passed between threads and kept in a set without surprises. *Source:* [dataclasses].
- **Configuration models are pydantic** models derived from `FrozenModel` (`extra="forbid"`, `frozen=True`). *Source:* ADR-0008.
- **A closed set of string values is a `StrEnum` defined once** (`EventKind.DISPENSE`, `EndQuality.SIGNAL_LOST`). Never `Literal` aliases or plain string constants for a closed set, and never two copies of the same set; other packages import the one definition. *Why:* one named definition can be imported, iterated and renamed in one place, and its members are still strings for the database, the logs and the configuration files (pydantic validates them). A closed set of numbers (baud rates) stays a `Literal`. *Source:* [enum] ("members are also strings"), [Literal] (a type checker treats an enum as the union of its members, so a `StrEnum` is checked as strictly as a `Literal`), project decision (2026-10-15).
- **Interfaces as `typing.Protocol` only where there are two implementations** (production and test). *Source:* ADR-0006 (level L2).
- **Prefer `Sequence`/`Mapping` in parameters and concrete types in return values.** *Why:* the caller may pass a tuple or a list; the result is exact. *Source:* [typing] (abstract collection types).

## 6. Functions and classes

- **A function does one thing.** When it passes about 40 lines, check whether it can be split without hurting the structure. *Source:* [GSG] §3.18.
- **Dependencies come in through parameters**, never through module globals. Clock, waiting, connections and ID factories are injected, with production defaults where that keeps the call simple. *Why:* the test builds the same object with a fake. *Source:* ADR-0008 (composition root), [GSG] §2.5 (no mutable global state).
- **Arguments are named wherever position alone does not explain them:** constructors with several dependencies take keyword-only arguments (`*`); dataclasses with more than three fields use `kw_only=True`; a boolean parameter is always keyword-only. *Why:* a call like `ClosedEvent(1, 3, 2_002, 500, ...)` cannot be read without opening the definition, and swapping two values of the same type passes silently. *Source:* [ruff] FBT001, PLR0913, [dataclasses] `kw_only`, project decision (2026-10-15).
- **Every parameter is used.** A parameter required by a protocol but not needed by one implementation is named with a leading underscore (`_wall_ns`). *Why:* an unused parameter makes the reader look for a purpose that does not exist. *Source:* [ruff] ARG001, ARG002.
- **No boolean flags that switch a function between two behaviours**; write two functions. *Why:* a call `feed(tank, True, False)` says nothing to the reader. *Source:* [ruff] FBT001 ("the meaning of the boolean value is not clear to the caller").
- **No mutable default arguments.** *Source:* [GSG] §2.12.
- **Return statements are consistent:** either every branch returns a value or none does. *Source:* [PEP8] §Programming Recommendations.
- **Exit codes are named constants defined once** (`EXIT_OK`, `EXIT_FAILURE`, `EXIT_CONFIG_ERROR`) and shared by all entry points. *Source:* project convention (no magic numbers).
- **State that other objects read is exposed through a read-only property**, not a public mutable attribute. *Source:* [PEP8] §Designing for Inheritance, [GSG] §2.13.

## 7. Constants and configuration

- **No magic numbers:** a number with meaning gets a named module constant. Tests may use literals where a name adds nothing. Ruff's `PLR2004` checks only comparisons; the rest is the reviewer's job. *Source:* [ruff] PLR2004, project decision.
- **Device and run-time parameters are configurable:** a named default (`DEFAULT_*`) that configuration, a model field or a CLI argument can override. *Why:* the plant changes, and a value in code needs a release. *Source:* project decision (2026-10-13), ADR-0008.
- **Configuration is read once, at start, by the entry point**, validated as a whole, and passed down as frozen objects. *Source:* ADR-0008.
- **Errors in configuration and scenarios are collected, not raised one by one:** each check returns a list of messages with the path of the field (`tanks[1].refill.pin: ...`), and one exception carries the whole list. *Why:* the operator fixes everything in one pass. *Source:* ADR-0008.

## 8. Errors and exceptions

- **Classes of errors decide the reaction** (ADR-0011, ADR-0015): a problem of one device or one record degrades the service and it keeps working; a problem the code cannot repair ends the process and systemd restarts it.
- **Own exceptions derive from `Exception`**, carry data as attributes (`errors`, `files`, `lost_records`) and live in the package that raises them. *Source:* [PyTut] §8.6, [GSG] §2.4.
- **Translate errors at the border** of a library: the module that talks to psycopg or pyserial turns their exceptions into the project's classes (`TransientStoreError`, `DataStoreError`). The rest of the code doesn't import library exceptions. *Why:* the reaction depends on our classification, not on the library's class tree. *Source:* [GSG] §2.4, ADR-0015.
- **Chain exceptions on translation** (`raise ... from error`); use `from None` only when the original error adds nothing for the reader. *Source:* [PyTut] §8.5.
- **Catch `Exception` only at the top of a thread**, to log it and re-raise. Everywhere else catch the narrowest class you can handle. *Source:* [GSG] §2.4, [ruff] BLE001.
- **Never swallow an error silently.** Suppressing (`contextlib.suppress`) is allowed only for cleanup that may fail after the real error was already handled (closing a broken port). *Source:* project convention.

## 9. Logging

- **Every log line is a named event** from `dms.logs.events` (`area.event`), never free text; details go in fields. A new event needs a row in [log-events.md](log-events.md); a test keeps both in sync. *Source:* ADR-0012.
- **Level says what happened to the data:** DEBUG single frames, INFO state changes, WARNING degradation the service recovers from, ERROR something lost for good, CRITICAL the service cannot go on. *Source:* ADR-0012.
- **Log transitions, not states:** start and end of a silence, with its duration; repeated events at the first one and then every N-th. *Source:* ADR-0012.
- **Logger:** one module logger `logger = structlog.get_logger()`; an object that logs for one device binds its context once in `__init__` (`self._logger = logger.bind(device_id=..., port=...)`). *(Decided by Claude; see the decision register.)* *Source:* [logging-howto] (module-level logger), [structlog] (`bind`).
- **Errors in log fields are `str(error)`**; a traceback goes through the logger's exception support, not `repr` in a field. *Source:* project convention.

## 10. Threads, queues and time

- **Threads share no mutable state.** They talk through `queue.Queue[T]` with a declared message type, and stop through `threading.Event`. The one exception is the shutdown flag of the main thread (below). *Why:* the domain has one owner thread, so it needs no locks. *Source:* ADR-0001, ADR-0004.
- **Thread loop shape:** `run()` loops `while not stop_event.is_set(): step()`, then drains and cleans up; `step()` does one unit of work and is what unit tests call. *Source:* project convention.
- **A thread with a stop event waits on it** (`stop_event.wait(timeout)`), never with `time.sleep()`, so a stop request ends the wait at once. *Source:* ADR-0011.
- **The main thread waits for shutdown on a plain flag with `time.sleep()`.** The signal handler (and the hook for a crashed thread) only sets the flag. *Why:* `Event.set()` in a signal handler can deadlock, because the handler runs in the main thread, which may at that moment hold the event's internal lock inside `Event.wait()`. *Source:* [signal] (handlers run in the main thread between bytecode instructions), project decision (P0).
- **The domain never reads the clock or does I/O.** Everything periodic or external comes in as a message with its own timestamps. *Source:* ADR-0004.
- **Time is integer nanoseconds inside the program** (`int` from `time.time_ns()`/`time.monotonic_ns()`, through the `Clock` protocol). Seconds as `float` appear only in configuration and at calls to the standard library that want seconds. *Why:* one unit and no rounding of float time. *Source:* project convention, ADR-0004.
- **Shutdown is a cascade:** producers, then engine (drains its queue), then writer (flushes). Start goes in the reverse order. *Source:* ADR-0011.

## 11. Database access

- **SQL is plain text in named module constants** (`INSERT_METER_READING_SQL`). Values always go through parameters (`%s`). Names of tables or schemas built at run time go through `psycopg.sql.Identifier`, never f-strings. *Why:* string formatting of SQL is "an accident waiting to happen". *Source:* [psycopg-sql].
- **`INSERT` lists its columns; no `SELECT *`.** *Why:* an added column must not break existing code. *Source:* ADR-0014 point 6.
- **Records the writer stores in batches are written idempotently** (`ON CONFLICT DO NOTHING` or an upsert by key), so a batch can be repeated after an error. Other writes don't have to be: starting a service run adds a new row on purpose. *Source:* ADR-0015.
- **A startup step that changes several tables runs in one transaction.** *Source:* ADR-0015.

## 12. Migrations

- **File name `NNNN_name.sql`**, numbers continuous from `0001`; the first line declares the change: `-- schema-change: major|minor|patch`. `dms-migrate` and a test check both. *Source:* ADR-0014.
- **A migration that reached `main` is never edited**; a fix is a new migration. Before the first deployment on a plant, migrations of one pull request are squashed into one file. *Source:* ADR-0014 points 3 and 8.
- **Privileges are granted in the migration that creates the object:** writes to `dms_writer` by explicit `GRANT`, reads come from `ALTER DEFAULT PRIVILEGES` for `dms_read`. A test checks each role. *Source:* ADR-0014 point 9.
- **Compatible changes:** a MINOR change adds nullable columns or columns with `DEFAULT`; removing goes in two steps (expand, then contract). *Source:* ADR-0014 point 6.

## 13. Tests

- **Levels** follow the directory under `tests/` and set the marker: `unit` (one module or one object, no database, serial port, network or real time; temporary files in `tmp_path` are allowed), `integration` (several components together, or a real external resource such as PostgreSQL or a pseudo-terminal), `e2e` (a service run as a process). *Source:* `testy.md`, `pyproject.toml`, [pytest-good].
- **A test name is a sentence about behaviour:** `test_lost_signals_close_the_open_event_at_the_last_fresh_snapshot`. *Why:* a failing test should say what broke without opening it. *Source:* project convention.
- **Arrange, act, assert, each block separated by a blank line**; one action under test. *Source:* [pytest-anatomy] ("Act is the singular, state-changing action").
- **Shared fixtures go to `conftest.py`** of the lowest directory that needs them; shared builders to `builders.py`, shared fakes to `tests/fakes.py`. A helper is never copied into a second test file. *Source:* [pytest-fixtures] (sharing via `conftest.py`).
- **Fixtures that need cleanup use `yield`.** *Source:* [pytest-fixtures].
- **Tests are deterministic:** time comes from `ManualClock` or a fake `wait`, IDs from a counter, randomness is not used. A test that must wait for a real process polls with a timeout instead of sleeping a fixed time. *Source:* ADR-0004, `testy.md`.
- **Test through the public interface.** A test doesn't read or write private attributes; if it needs to, the object lacks a method. *Source:* [ruff] SLF001.
- **Test doubles are small classes that implement the protocol.** The name says what the class stands in for (`FakePort`, `FakeWriter`) or how it behaves (`ManualClock`, `ScriptedOpener`). `monkeypatch` only for module functions at a border (for example the database call in `startup`). *Source:* project convention.
- **Parametrized cases have readable ids** that say what the case is (`"tank-in-unknown-silo"`), not codes from a plan. *Source:* [pytest-parametrize].
- **Domain values in tests are built with keyword arguments** like everywhere else (§6), so an expected record reads field by field. *Source:* project decision (2026-10-15).
- **The simulator is the source of test traffic** for integration and e2e tests: scenarios from the catalogue, frames from its encoders, expected events from `expected_events`. *Source:* `testy.md` §2.
- **Literal numbers in tests are allowed** (`PLR2004` is off for `tests/`), but units come from shared constants (`NS_PER_S`), not local copies. *Source:* `pyproject.toml`.

## Sources

- [PEP8] PEP 8 — Style Guide for Python Code. https://peps.python.org/pep-0008/
- [PEP257] PEP 257 — Docstring Conventions. https://peps.python.org/pep-0257/
- [PEP695] PEP 695 — Type Parameter Syntax. https://peps.python.org/pep-0695/
- [GSG] Google Python Style Guide. https://google.github.io/styleguide/pyguide.html
- [PyTut] The Python Tutorial, chapter 8 "Errors and Exceptions". https://docs.python.org/3/tutorial/errors.html
- [dataclasses] Python documentation, `dataclasses`. https://docs.python.org/3/library/dataclasses.html
- [enum] Python documentation, `enum` (`StrEnum`). https://docs.python.org/3/library/enum.html
- [Literal] Typing specification, Literal types. https://typing.python.org/en/latest/spec/literal.html
- [typing] Python documentation, `typing` and `collections.abc`. https://docs.python.org/3/library/typing.html
- [mypy] mypy command line reference, `--strict`. https://mypy.readthedocs.io/en/stable/command_line.html
- [ruff] Ruff rules. https://docs.astral.sh/ruff/rules/
- [signal] Python documentation, `signal` (execution of Python signal handlers). https://docs.python.org/3/library/signal.html
- [logging-howto] Python Logging HOWTO. https://docs.python.org/3/howto/logging.html
- [structlog] structlog, Getting Started. https://www.structlog.org/en/stable/getting-started.html
- [psycopg-sql] psycopg 3, `sql` — SQL string composition. https://www.psycopg.org/psycopg3/docs/api/sql.html
- [pytest-anatomy] pytest, Anatomy of a test. https://docs.pytest.org/en/stable/explanation/anatomy.html
- [pytest-fixtures] pytest, How to use fixtures. https://docs.pytest.org/en/stable/how-to/fixtures.html
- [pytest-good] pytest, Good Integration Practices. https://docs.pytest.org/en/stable/explanation/goodpractices.html
- [pytest-parametrize] pytest, How to parametrize fixtures and test functions. https://docs.pytest.org/en/stable/how-to/parametrize.html
- Project documents in the [dms-docs](https://github.com/AndrzejJanaszek/dms-docs) repository (private, in Polish):
  - [ADR-0001](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0001-wariant-b-przeplyw-komunikatow.md) message flow
  - [ADR-0004](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0004-silnik-bez-zegara-i-io.md) engine without clock and I/O
  - [ADR-0006](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0006-struktura-paczek-i-porty.md) packages and ports
  - [ADR-0008](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0008-konfiguracja-i-composition-root.md) configuration and composition root
  - [ADR-0011](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0011-odpornosc-i-poziomy-krytycznosci.md) resilience and criticality levels
  - [ADR-0012](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0012-logowanie-strukturalne.md) structured logging
  - [ADR-0014](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0014-migracje-i-role-w-bazie.md) migrations and database roles
  - [ADR-0015](https://github.com/AndrzejJanaszek/dms-docs/blob/main/adr/0015-semantyka-writera.md) writer semantics
  - [testy.md](https://github.com/AndrzejJanaszek/dms-docs/blob/main/testy.md) test strategy
