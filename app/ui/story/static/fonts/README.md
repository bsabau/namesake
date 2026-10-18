# Nunito and Fraunces, self-hosted

The story UI's typefaces. Served from this folder so a visitor's browser makes no request to a font service.

- **Nunito** (variable weight), by Vernon Adams, Cyreal and Jacques Le Bailly: the interface and body text. Licence: SIL Open Font License 1.1, in `OFL.txt`. Source: the npm package `@fontsource-variable/nunito` 5.3.0, fetched 18 October 2026; the same files as `app/ui/warm/static/fonts/`.
- **Fraunces** (variable weight), by Undercase Type (Phaedra Charles and Flavia Zimbardi): the headlines, the animal's name and the introduction. Licence: SIL Open Font License 1.1, in `OFL-fraunces.txt`. Source: the npm package `@fontsource-variable/fraunces` 5.2.8, fetched 18 October 2026.
- Files: the `latin` and `latin-ext` subsets only. Their `unicode-range` is in `../style.css`, copied from each package's `index.css`.

| File | sha256 |
|---|---|
| `nunito-latin-wght-normal.woff2` | `ba344451eab25b217a165363b1982048a5e5830a0daf36577973955a04cac793` |
| `nunito-latin-ext-wght-normal.woff2` | `2c8d792869818ecb253a46bc3c63c7013df7aac2f69291c3c85e5cdc94160960` |
| `fraunces-latin-wght-normal.woff2` | `7f9d191d999336d3b9790afa72e1358e50a13b06d4f289341e92a311967a80f9` |
| `fraunces-latin-ext-wght-normal.woff2` | `a21ecfbf41fbc393e24ef9b7e38532a27e8da5e0a074aa7d66802d1b5ccec2f0` |

To refetch, in an empty directory outside the repository:

```sh
npm pack @fontsource-variable/nunito@5.3.0 @fontsource-variable/fraunces@5.2.8
tar -xzf fontsource-variable-nunito-5.3.0.tgz && mv package nunito
tar -xzf fontsource-variable-fraunces-5.2.8.tgz && mv package fraunces
shasum -a 256 nunito/files/nunito-latin*-wght-normal.woff2 fraunces/files/fraunces-latin*-wght-normal.woff2
cp nunito/files/nunito-latin-wght-normal.woff2 nunito/files/nunito-latin-ext-wght-normal.woff2 app/ui/story/static/fonts/
cp fraunces/files/fraunces-latin-wght-normal.woff2 fraunces/files/fraunces-latin-ext-wght-normal.woff2 app/ui/story/static/fonts/
cp nunito/LICENSE app/ui/story/static/fonts/OFL.txt
cp fraunces/LICENSE app/ui/story/static/fonts/OFL-fraunces.txt
```
