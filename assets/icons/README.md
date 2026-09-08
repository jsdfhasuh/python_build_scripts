# VisionWorkshop icon

Place the approved production icon at `assets/icons/visionworkshop.ico`, or pass
`--icon-path` with an existing ICO path. The profile deliberately fails when its
required icon is missing. No production icon has been supplied in this change.

A real ICO is required, not a PNG renamed to `.ico`. All contained PNG/DIB images
are bounds-checked and decoded using Pillow in the build environment. This does
not convert images or add a new runtime dependency to the application.

The generated icons under `tests/branding_fixtures.py` are test data only. Do not
copy them into a production release or present them as the approved application icon.
