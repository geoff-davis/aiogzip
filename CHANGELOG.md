# Changelog

All notable changes to this project will be documented in this file.

## [0.4] - Unreleased

- Fix handling of negative `size` values so reads return the full remaining payload in both binary and text modes.
- Make `AsyncGzipTextFile.write()` report the number of characters written instead of encoded byte counts.
*** End Patch
