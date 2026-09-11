# VisionWorkshop Assets

`icons/visionworkshop.ico` is an unmodified copy of the user-supplied
`VisionWorkshop_icons/VisionWorkshop_icons/app.ico`, added on 2026-09-08.
It contains the supplied 16, 20, 24, 32, 40, 48, 64, 96, 128 and 256 pixel frames.

SHA256: `da7c8a8edd09e8c59a51e321beeeaadf518c174a0a2d48bfa0bf582e3bc1164d`.

`branding.json` supplies the application display name and a configuration-relative
window icon path. The opt-in profile packages both files into the main application
resource root. The same ICO is embedded in the main executable, named updater and
legacy launchers. The named updater also bundles the branding resources so it can
read its display name without importing the application. These are not test fixture assets.
