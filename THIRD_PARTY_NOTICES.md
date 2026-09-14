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
