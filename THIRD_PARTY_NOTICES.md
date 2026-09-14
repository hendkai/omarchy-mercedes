# Third-party notices

## mbapi2020 — MIT

The 12 generated protobuf modules in `omarchy_mercedes/vendored/` originate
from https://github.com/ReneNulschDE/mbapi2020 at commit
`aa6e9453a5da1cff79c8f427ccfcf079a06f247f` (`custom_components/mbapi2020/proto/`).
Imports were rewritten to package-relative imports. Wire descriptors are retained.
The OAuth/telemetry implementation was developed using that upstream behavior
as a reference. Upstream license, pinned:
https://github.com/ReneNulschDE/mbapi2020/blob/aa6e9453a5da1cff79c8f427ccfcf079a06f247f/LICENSE

MIT License

Copyright (c) 2026 Rene Nulsch

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

## gogoproto schema — BSD 2-Clause

`gogo_pb2.py` contains the `gogoproto` extensions to descriptor.proto. The
schema originates from GoGo Protocol Buffers. Extension names, numbers,
types and extendees were compared with the v1.3.2 source:
https://github.com/gogo/protobuf/blob/v1.3.2/gogoproto/gogo.proto
This identifies schema provenance, not a claim that the upstream maintainer
used that exact compiler/tag to generate the Python file.

Protocol Buffers for Go with Gadgets

Copyright (c) 2013, The GoGo Authors. All rights reserved.
http://github.com/gogo/protobuf

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

    * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Protocol Buffers runtime

The separately installed `protobuf` dependency has its own BSD 3-Clause
license and packaged notices: https://github.com/protocolbuffers/protobuf/blob/main/LICENSE
Its terms are not replaced by this project's MIT license.

MIT and the retained BSD notices permit redistribution under their conditions;
this is not a legal certification. No Mercedes-Benz logos are included. This
is an unofficial project, not affiliated with Mercedes-Benz Group AG.
