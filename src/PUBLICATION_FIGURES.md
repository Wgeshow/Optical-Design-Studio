# Publication figures

Every desktop Matplotlib plot now fits its available space without stretching
the configured figure proportions. XY/XZ field maps and 2D geometry sections
use equal physical scaling. 3D geometry uses physical axis ranges with an
orthographic camera; thin structures are no longer artificially thickened.

Choose **Figure settings** in a plot toolbar to configure:

- Physical width and height in millimetres, with single-column, double-column,
  and square presets.
- Font family and separate point sizes for titles, axis labels, ticks, and legends.
- Line width, axes width, and marker size in points.
- Panel titles, axis/colorbar labels, curve legend names, colors and line styles.
- Raster DPI and an optional saved default style for future figures.

Default style: 180 × 110 mm, DejaVu Sans, 10 pt axis labels, 9 pt tick labels,
11 pt titles, 8.5 pt legends, 1.5 pt lines, 0.8 pt axes and 600 DPI.
Match physical dimensions and fonts to the destination journal's requirements.

The toolbar Save icon exports **PDF**, **SVG**, **PNG**, or **TIFF**. PDF embeds
TrueType text and SVG keeps text editable. PDF/SVG preserve vector lines; field
meshes may produce large vector files. PNG/TIFF use the configured DPI. Exports
have a white background and dark labels regardless of the application's theme.
They use the specified paper dimensions, not the current screen or window size.

Data values are not smoothed or interpolated by styling. Sample density, Fourier
basis convergence, physical validity, and correct scientific interpretation
still require verification. Image quality alone does not establish those.
