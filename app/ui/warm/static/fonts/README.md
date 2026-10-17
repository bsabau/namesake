# Nunito, self-hosted

The warm UI's typeface. Served from this folder so a visitor's browser makes no request to a font service.

- Family: Nunito (variable weight), by Vernon Adams, Cyreal and Jacques Le Bailly.
- Licence: SIL Open Font License 1.1, in `OFL.txt` beside the files.
- Source: the npm package `@fontsource-variable/nunito` 5.3.0, fetched 18 October 2026.
- Files: the `latin` and `latin-ext` subsets only. Their `unicode-range` is in `../style.css`, copied from the package's `index.css`.

| File | sha256 |
|---|---|
| `nunito-latin-wght-normal.woff2` | `ba344451eab25b217a165363b1982048a5e5830a0daf36577973955a04cac793` |
| `nunito-latin-ext-wght-normal.woff2` | `2c8d792869818ecb253a46bc3c63c7013df7aac2f69291c3c85e5cdc94160960` |

To refetch, in an empty directory outside the repository:

```sh
npm pack @fontsource-variable/nunito@5.3.0
tar -xzf fontsource-variable-nunito-5.3.0.tgz
shasum -a 256 package/files/nunito-latin-wght-normal.woff2 package/files/nunito-latin-ext-wght-normal.woff2
cp package/files/nunito-latin-wght-normal.woff2 package/files/nunito-latin-ext-wght-normal.woff2 app/ui/warm/static/fonts/
cp package/LICENSE app/ui/warm/static/fonts/OFL.txt
```
