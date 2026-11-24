# Document parser provenance

The current supported versions are pinned in [the reader manifest](../requirements-documents.txt). Hosted CI checks those exact releases against GitHub's reviewed advisories and runs the offline parser suites on Windows. The PDF pin moved to 6.21.4 to address high-severity PDF parsing advisories affecting 6.10.0. [Page tree advisory](https://github.com/py-pdf/pypdf/security/advisories/GHSA-cggf-277g-3q54)

## PDF reader delivered with the release

Process Collector uses pypdf 6.21.4 for indexing and for producing individual pages for review. It reuses that exact version when available in the selected interpreter. Otherwise it verifies the release's upstream wheel and imports directly from the archive. If another library has already loaded a different version, Process Collector sends the PDF operation to its isolated reader process. The previous library stays available to its original caller.

On November 23, 2026, the official `pypdf-6.21.4-py3-none-any.whl` was verified against PyPI. The archive is 410,430 bytes and its SHA-256 is `33e4fb41ca352810eb4e9838aa0d82d6888a5f8bf682f43e99cce5faa666255c`. The wheel contains the BSD-3-Clause license in `pypdf-6.21.4.dist-info/licenses/LICENSE`. The wheel is kept in the repository's `vendor/` folder, so an offline launch uses the resource that belongs to its version. The application build identity includes its binary contents. [Official PyPI release files](https://pypi.org/project/pypdf/6.21.4/#files)

## Historical local digests


This Windows x64 Python 3.12 baseline records the executable package files used in the offline release checks. The optional lxml backend was available to openpyxl; defusedxml was unavailable. The app independently rejects XML entities and DTDs in every workbook ZIP member. Python, SQLite, package metadata, bytecode, and external application data are excluded from the following package digests.

The digest covers all installed package-relative files whose extension is .py, .pyd or .dll, excluding parent-directory entries and metadata. Compute the SHA-256 of each file, sort pairs of POSIX relative path and lowercase hex digest by path, encode the list with Python json.dumps(separators=(',', ':')).encode(), and take its SHA-256. Compiled dependencies have platform-specific digests.

| Distribution | Installed version | Files | SHA-256 |
| --- | --- | ---: | --- |
| pypdf | 6.10.0 | 55 | `78c4948a0fff3cafb6534fcc43eefe2701304076055ecfe2f401cb5cbe018875` |
| openpyxl | 3.1.5 | 190 | `6590c5fbe23e728d3c30fa28b61ebf2970986eff3b36246168843c654c0819f8` |
| Pillow | 13.0.0 | 105 | `09472ccc3786db601de61b6f1ec5d7bf01e17f234cb48dfd952656e2966d2e44` |
| et_xmlfile | 2.0.0 | 3 | `cc41d955fece73fdd0d4f6b259dc5c1191ce43a0e65f5d28368cba9768624eca` |
| lxml | 6.1.1 | 36 | `e43d788064bd7b68548d560ca98546361fe710484861ed903fa69f6754d30af6` |
