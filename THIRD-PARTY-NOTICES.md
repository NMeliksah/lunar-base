# Third-Party Notices

Lunar Base bundles and links code from other projects. Their licences and
copyright notices are reproduced below, as those licences require.

---

## Lunar Tear

<https://github.com/Walter-Sparrow/lunar-tear>

The `lunar-base-grant` shim (`tools/grant/src/`) imports Lunar Tear's
internal packages, and the compiled binary shipped in release archives
(`tools/grant/grant`, `tools/grant/grant.exe`) contains Lunar Tear code
linked into it. Every database write Lunar Base performs goes through
these functions rather than through SQL of its own.

```
MIT License

Copyright (c) 2026 Ilya Groshev

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## lunar-scripts

<https://gitlab.com/walter-sparrow-group/lunar-scripts>

`tools/dump_masterdata.py` and `tools/schemas.json` originate from this
repository. They are included so Lunar Base can decode master data without
requiring a separate checkout.

At the time of writing the repository carries no licence file. These files
are included in good faith and with attribution to their author; if the
author would prefer they not be redistributed, open an issue and they will
be removed, with the launcher fetching them at setup time instead.

---

## Go standard library and module dependencies

The compiled shim statically links the Go standard library and the modules
listed in Lunar Tear's `go.mod`, including `modernc.org/sqlite`,
`github.com/google/uuid`, `github.com/pierrec/lz4`, and
`github.com/vmihailenco/msgpack`. All are distributed under BSD-3-Clause or
MIT terms. Their full licence texts ship inside the Go module cache and are
available from each project's repository.

---

## Game assets and data

Lunar Base ships no game content. Master data, text bundles, and save
databases are read from a Lunar Tear installation the user supplies. All
game assets remain the property of their respective rights holders.
