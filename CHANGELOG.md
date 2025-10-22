# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.3] - 2025-10-21

- Fix handling of negative `size` values so reads return the full remaining payload in both binary and text modes.
- Make `AsyncGzipTextFile.write()` report the number of characters written instead of encoded byte counts.
- Normalize iteration errors from `AsyncGzipBinaryFile` to `TypeError`, matching the standard file API.
- Declare project metadata dynamically via `aiogzip.__version__`, add explicit license info, and tidy packaging configuration.
