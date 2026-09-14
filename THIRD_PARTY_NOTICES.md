# Third-party notices

## mbapi2020 (MIT)

This project vendors generated protobuf modules (`omarchy_mercedes/vendored/*_pb2.py`)
that originate from https://github.com/ReneNulschDE/mbapi2020
(Copyright Rene Nulsch and contributors, MIT License).

The modules describe the wire format of the (unofficial) Mercedes-Benz
mobile SDK telemetry API. Import statements were rewritten from
`custom_components.mbapi2020.proto.*` to relative imports; the generated
code itself is unchanged.

Source license: https://github.com/ReneNulschDE/mbapi2020/blob/master/LICENSE

The OAuth2 flow in `omarchy_mercedes/oauth_client.py` and the REST/widget
endpoints in `telemetry.py` were implemented from scratch against the
documented behavior of that project (no code copied).

## Protocol Buffers

The vendored `*_pb2.py` files are generated with protoc and depend on the
`protobuf` Python package (BSD 3-Clause, Google LLC).

## Runtime dependencies

Dependencies are installed separately, not relicensed by this repository:
`requests` (Apache-2.0), `protobuf` (BSD-3-Clause), and optional `keyring` (MIT).
The native widget runs in Omarchy/Quickshell and uses Qt; those projects retain
their own licenses. Consult the licenses shipped with the versions you install.

## Original artwork and trademarks

`omarchy-plugin/assets/electric-vehicle.svg` is original artwork created for this
project: a neutral car silhouette with a battery indicator and silver gradient.
It is released under the project's [MIT license](LICENSE), not a third-party
asset license. It contains no manufacturer logo or emblem, embeds no external
images or fonts, and uses no downloaded brand assets.

Mercedes-Benz names and trademarks belong to their respective owners. The MIT
license grants no trademark rights, brand approval, or endorsement. This is an
unofficial integration with no claimed affiliation; no official Mercedes-Benz
artwork is included or licensed by this project.
