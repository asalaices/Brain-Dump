# Bootstrap tests

Offline checks cover registration, plans, common runtime integrity, ownership,
telemetry redaction and compatibility with the existing runtime installer.
Future live and manual checks must reside under explicit `live/` and `manual/`
subdirectories and are never selected by the offline suite runner.
