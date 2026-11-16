# Changelog

## 2.0.0

### Fixed
- **Statistics corrupted by the daily update** (regression of v1.6.0): the overlapping window
  (first day of previous month → today) was re-imported on top of the latest total, creating a
  growing jump at the start of the window. The cumulative sum now continues from the value stored
  right before the window, so re-imports are idempotent. Existing statistics are rebuilt.
- Monthly sensor summed running totals instead of hourly values (hugely wrong value) and covered
  ~45 days instead of the current month.
- Daylight saving time: hours are converted from Italian time to UTC correctly (23/25 hour days);
  the October H25 no longer overwrites the next day's first hour, the March 02:00 hour is no longer lost.
- Historical import returned nothing during the first days of the month (empty current month),
  marked itself completed on errors, and never ran for new installations.
- Timer never cancelled on reload/unload; data fetched twice per day (entity polling + timer).
- HTTP sessions leaked when login failed; no request timeouts.
- Debug JSON files written forever into `/config/enelgrid_debug` from the event loop.
- Options flow never shown (defined outside the config flow class).
- User numbers with leading zeros were stored as integers.

### Changed
- Rewritten around a `DataUpdateCoordinator` (12h interval) with automatic re-authentication.
- Statistics metadata uses `mean_type` / `unit_class` (required by recent Home Assistant versions).
- Config entry keys renamed (`pod`, `user_number`) with UI translations (English, Italian).
- Price per kWh editable in the options; cost history before the re-imported window is preserved.
- Gap filling: if Home Assistant was offline, the update starts from the last stored hour (max 1 year).
- New sensors with unique ids and a device; diagnostics download replaces the debug files.
- `beautifulsoup4` dependency removed (stdlib HTML parser).
- Minimum Home Assistant version: 2025.11.

### Removed
- `restore_backup.py`, `verify_migration.sh`, `UPGRADE_1.4.0.md` (obsolete 1.4 migration tools).
- `enelgrid Daily Import` text sensor.
