# Vendored front-end files

Served as-is from `/static/vendor/`. None of these carries its version in the file, so it is
recorded here. A file was matched to its release by comparing its SHA-256 with the file the
package publishes (jsdelivr, 2026-09-20); each licence file is the one that package ships. Replace a file only together with its row, and keep
the xterm.js family on one release line: the addons are built against `@xterm/xterm`.

| file | package | version | licence |
|---|---|---|---|
| `xterm.js`, `xterm.css` | `@xterm/xterm` | 6.0.0 (matched 2026-11-17, TD-1918) | MIT (`LICENSE-xterm.txt`) |
| `addon-fit.js` | `@xterm/addon-fit` | 0.11.0 (the release paired with xterm 6.0.0) | MIT (`LICENSE-addon-fit.txt`) |
| `addon-webgl.js` | `@xterm/addon-webgl` | 0.19.0 (the release paired with xterm 6.0.0) | MIT (`LICENSE-addon-webgl.txt`) |
| `addon-web-links.js` | `@xterm/addon-web-links` | 0.12.0 (the release paired with xterm 6.0.0; first vendored 2026-10-08, TD-422) | MIT (`LICENSE-addon-web-links.txt`) |
| `addon-unicode-graphemes.js` | `@xterm/addon-unicode-graphemes` | 0.4.0 (the release paired with xterm 6.0.0; matched 2026-11-17, TD-1918) | MIT (`LICENSE-addon-unicode-graphemes.txt`) |
| `fonts/jetbrains-mono-latin-{400,700}-normal.woff2` | `@fontsource/jetbrains-mono` | 5.1.1, latin subset | SIL OFL 1.1 (`fonts/OFL.txt`) |
