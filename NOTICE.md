# NOTICE

This file is provided for informational purposes only.

It does not modify any license terms. The governing license for the project's original code and documentation is the root [LICENSE](LICENSE) file. Third-party components bundled in this repository remain under their own respective licenses.

## Repository licensing summary

Unless otherwise noted in a file, directory, or third-party notice:

- original code and documentation authored for `dptest-community-edition` are distributed under the Apache License, Version 2.0
- bundled third-party components are not relicensed under Apache-2.0
- bundled proprietary components are not licensed under Apache-2.0 and are not granted open-source redistribution rights by this repository
- recipients and redistributors must comply with the license terms of each bundled third-party component
- recipients and redistributors must not assume that bundled commercial binaries may be copied, redistributed, modified, reverse engineered, or used beyond the permissions separately granted by their owner

This repository is therefore a mixed-license distribution.

## Project notice

Project name:

- `dptest-community-edition`

Copyright notice:

- Copyright (c) 2026 dptest contributors

## Third-party components confirmed by local repository inspection

### `dptest-host-manager/igb_uio.tar.gz`

This repository bundles an `igb_uio` source archive used by the host-manager installation workflow.

Local inspection of the archived source file `igb_uio/igb_uio.c` shows:

- `SPDX-License-Identifier: GPL-2.0`
- `MODULE_LICENSE("GPL")`
- Intel copyright notice

Accordingly:

- `dptest-host-manager/igb_uio.tar.gz` must be treated as third-party GPL-2.0 code
- it is not relicensed under Apache-2.0
- if binaries or kernel modules built from this source are redistributed, the redistributor must comply with the obligations of the applicable GPL version for that component

## Bundled third-party runtime libraries in `dptest-engine-agent/lib64/`

The current repository includes prebuilt shared libraries under `dptest-engine-agent/lib64/`.

Based on the bundled file names and upstream project conventions, the library set currently appears to include the following third-party components:

| Bundled files | Likely upstream project | Expected license family | Notes |
| --- | --- | --- | --- |
| `libmicrohttpd.so.12*` | GNU libmicrohttpd | LGPL-2.1-or-later | Confirmed upstream project family; retain upstream notices when redistributing. |
| `libnuma.so.1*` | numactl / libnuma | LGPL-2.1 | Retain upstream notices when redistributing. |
| `libconfig.so.11*` | libconfig | LGPL family | Verify exact bundled version notice before tagged public release. |
| `libpcap.so.1*` | libpcap | BSD-style | Retain upstream license text when redistributing. |
| `libbsd.so.0*` | libbsd | permissive BSD/ISC/MIT-style mix | Verify bundled version notice set before tagged public release. |
| `libmd.so.0*` | libmd | permissive BSD-style family | Verify bundled version notice set before tagged public release. |
| `libmagic.so.1*` | file / libmagic | BSD-style | Retain upstream notice text when redistributing. |
| `libpcre.so.1*` | PCRE 8.x family | BSD-style | Verify exact bundled version notice before tagged public release. |
| `libfreebl3.so` | Mozilla NSS / FreeBL family | Mozilla public-license family | Verify exact bundled version licensing and notice text before tagged public release. |

Important note:

- The entries above identify the most likely upstream components and license families based on current repository inspection.
- Before a formal public release, maintainers should verify the exact upstream version and ship the corresponding third-party license texts for the exact binaries included in the repository.

## Other bundled third-party material that requires license review

### `dptest-host-manager/dpdk-devbind.py`

This file appears to be derived from DPDK tooling and should retain its original upstream copyright and license notices.

Before a tagged public release:

- verify the exact upstream source and version
- preserve the exact upstream copyright notice
- preserve the exact upstream license text required for redistribution

### `dptest-engine-agent/app/dpdkproxy`

This repository bundles a prebuilt engine binary.

`dpdkproxy` is a proprietary commercial engine component.

Unless the copyright owner separately grants rights in writing:

- `dpdkproxy` is not licensed under Apache-2.0
- this repository does not grant permission to copy `dpdkproxy`
- this repository does not grant permission to redistribute `dpdkproxy`
- this repository does not grant permission to create derivative works of `dpdkproxy`

Anyone using or redistributing this repository should treat `dpdkproxy` as a rights-reserved binary and obtain any required commercial permission directly from its owner.

### Certificate and key material

The repository contains certificate and key material under paths including:

- `dptest-engine-agent/cert/`
- `dptest-engine-agent/uconf/cert_keys/`

Before a tagged public release, maintainers should verify:

- whether each file is sample or test-only material
- whether each file is safe for public redistribution
- whether any private, internal, or non-public material should be removed or regenerated

## Redistribution guidance

Anyone redistributing this repository, a fork of it, or a binary package derived from it should:

1. include the root [LICENSE](LICENSE) file
2. preserve this `NOTICE.md` file
3. preserve file-level and directory-level license notices from third-party components
4. comply with the license terms of bundled third-party components, including copyleft obligations where applicable
5. avoid stating or implying that all repository contents are covered solely by Apache-2.0
6. avoid stating or implying that `dptest-engine-agent/app/dpdkproxy` is open source or freely redistributable

## Recommended follow-up for maintainers

Before a formal public release, consider adding:

- a `third_party/licenses/` directory containing the full text of the licenses required by bundled third-party components
- file-level copyright and SPDX headers for original project files
- a release checklist for bundled binaries, libraries, scripts, and certificate material
