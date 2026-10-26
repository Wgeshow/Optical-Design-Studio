# Optical Design Studio 1.3.3

Extract the entire portable 7z archive using 7-Zip. Run Optical Design Studio.exe with OpticalDesignBackend.exe and the _internal folder beside it. No separately installed Python is needed.

This is the Absolute Phase Fix snapshot, rebuilt with the 1.3.3 release identity. See RELEASE_NOTES.md and VALIDATION.json for changes, completed checks, and scientific limitations.

Keep a backup of existing User Data and any configured library before updating. This release contains an empty seed library and the public help tutorial; it does not include personal sessions or simulation libraries.

Corresponding readable application source is in _internal/source. The separate source archive also includes the build recipe and native source. Optional GPU, CAD, electrical and external-solver features have their own runtime requirements and scope; see the included guides.
