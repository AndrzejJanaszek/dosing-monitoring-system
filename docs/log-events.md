# Log events

Every log line has an `event` name from this catalogue. The names are constants in `dms.logs.events`; a test checks that the code and this file list the same events. A new event needs a row here.

| event | level | fields | meaning | action |
|---|---|---|---|---|
| `service.started` | INFO | `run_id` | The service finished startup and is collecting data. | none |
| `service.stopped` | INFO | `run_id` | The service shut down cleanly. | none |
| `service.stop_incomplete` | ERROR | `run_id` | The service stopped after a crash, a thread did not finish in time or the writer lost records; `run.stopped_at` stays empty and the process exits with code 1. | read the preceding errors |
| `config.invalid` | CRITICAL | `errors` | A configuration file is missing or invalid; the process exits with code 2. | fix the files named in `errors` |
| `db.connect_retry` | WARNING | `role`, `attempt`, `error` | The database does not accept the connection yet; the process retries. | check that PostgreSQL is running |
| `db.connected` | INFO | `role`, `dbname` | The database connection was established. | none |
| `db.schema_incompatible` | CRITICAL | `database_version`, `package_version` | The database schema does not match the installed package; startup is refused. | run `dms-migrate` or install the matching package |
| `db.startup_failed` | CRITICAL | `step`, `error` | A startup step against the database failed; startup is refused. | read `error`, fix and restart |
| `db.write_error` | WARNING | `error`, `batch_size` or `context` | Writing a batch failed with a transient error; the writer reconnects and retries. | check the database if it does not recover |
| `db.write_recovered` | INFO | `outage_s` | Writing resumed after a transient error. | none |
| `db.readings_skipped` | WARNING | `skipped`, `batch_size` | Some readings of a batch were not inserted because a reading with the same silo and timestamp already exists (for example after the system clock stepped back). | check time synchronisation if it repeats |
| `writer.fatal` | CRITICAL | `error` | The writer hit an error it cannot recover from; the process exits. | read `error`, fix the cause (for example a full disk) |
| `writer.abandoned` | ERROR | `lost_records` | The service is stopping while the database is unreachable; the writer gives up after one last attempt and the records are lost. `run.stopped_at` stays empty and the process exits with code 1. | check the database; the gap in `meter_reading` is expected |
| `engine.fatal` | CRITICAL | `error` | The engine hit an unexpected error; the process exits. | report the traceback |
| `thread.crashed` | CRITICAL | `thread`, `error` | An unhandled exception ended a thread; the process exits with code 1. | report the traceback; systemd restarts the service |
| `port.opened` | INFO | `meter_id`, `port` | A serial port was opened. | none |
| `port.open_failed` | WARNING | `meter_id`, `port`, `error` | A serial port cannot be opened; logged on the first failure of a series. | check the cable and the configured port path |
| `port.disconnected` | WARNING | `meter_id`, `port`, `error` | Reading from a serial port failed; the adapter reconnects. | check the cable |
| `port.silence` | WARNING | `meter_id`, `silence_timeout_s` | No valid frame arrived within the silence timeout; the adapter forces a reconnect. | check that the meter is powered and sending |
| `port.silence_ended` | INFO | `meter_id`, `duration_s` | A valid frame arrived after a silence. | none |
| `port.garbage` | WARNING | `meter_id`, `rejected_count` | Frames that do not parse arrive; logged for the first one and then every 100th. | check baud rate and output format of the meter |
| `meter.out_of_range` | WARNING | `meter_id`, `port`, `status` | The meter reports overload (`OL`) or underload (`UL`); no reading is published, the port counts as alive. Logged when the state starts or changes. | check the load cell and the silo |
| `meter.back_in_range` | INFO | `meter_id`, `port`, `status` | The meter sends weights again after an overload or underload. | none |
| `migrate.applied` | INFO | `migration`, `schema_version` | One migration file was applied. | none |
| `migrate.done` | INFO | `schema_version`, `applied_count` | All migrations are applied. | none |
| `migrate.checksum_mismatch` | CRITICAL | `files` | An applied migration file was changed; the database is untouched. | restore the files; never edit an applied migration |
| `migrate.database_ahead` | CRITICAL | `migrations` | The database has migrations the package does not know. | install the newer package |
