# OAST-Community

Standalone OAST client for the public **Burp Collaborator** infrastructure.

OAST-Community generates reusable out-of-band payloads and retrieves DNS and HTTP(S) interactions without requiring Burp Suite Professional.

The client uses a persistent Collaborator context, allowing multiple payloads to be generated and tracked from the same session. It also includes manual polling and a continuous listener for incoming interactions.

No third-party Python packages are required.

> This is an unofficial project and is not affiliated with or endorsed by PortSwigger.

## What It Does

1. Creates or restores a local Collaborator client context.
2. Generates unique `*.oastify.com` OAST payloads.
3. Tracks multiple payloads under the same context.
4. Polls the public Collaborator infrastructure for new interactions.
5. Groups DNS callbacks to reduce duplicate resolver noise.
6. Parses DNS, HTTP, HTTPS and SMTP(S) interactions received by the OAST server.
7. Provides a continuous listener mode for real-time interaction monitoring.
8. Stores every received interaction locally so polled events are never lost.
9. Lets you browse past payloads and their interactions, with labels and notes.
10. Supports custom-data payloads to correlate interactions to injection points.
11. Shows full raw request/response and can save a report per payload.
12. Resolves source addresses with reverse DNS on demand.
13. Works against the public infrastructure or a private Collaborator server.
14. Persists the client context between executions.
15. Supports ephemeral sessions when persistence is not desired.
16. Uses only the Python standard library.

## Requirements

```bash
Python 3.10+
```

No third-party Python packages are required.

## Quick Start

Clone the repository:

```bash
git clone https://github.com/Groppoxx/OAST-Community.git
cd OAST-Community
```

Run the client:

```bash
python3 oast_community.py
```

The first execution creates a persistent client context automatically.

```text
╭────────────────────────────────────────────────────────────╮
│  OAST Community  v1.0.0                                    │
├────────────────────────────────────────────────────────────┤
│  Payloads  0                                               │
│  Latest    none                                            │
├────────────────────────────────────────────────────────────┤
│  [1] New payload                                           │
│  [2] Poll now                                              │
│  [3] Listen                                                │
│  [4] Payloads                                              │
│  [0] Exit                                                  │
╰────────────────────────────────────────────────────────────╯

Select >
```

## Usage

### Generate a Payload

Select:

```text
[1] New payload
```

Example:

```text
[2026-09-27T21:20:34Z] [+] Payload #1 generated

  4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com
```

The generated hostname can be used depending on the OAST sink being tested.

DNS:

```text
4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com
```

HTTP:

```text
http://4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com/
```

HTTPS:

```text
https://4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com/
```

For example:

```bash
curl "http://4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com/http-test"
```

or:

```bash
curl "https://4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com/https-test"
```

### Poll for Interactions

Select:

```text
[2] Poll now
```

Example output:

```text
[2026-09-27T21:25:07Z] [*] Polling for interactions
[2026-09-27T21:25:09Z] [+] 3 interactions received · 2 DNS · 1 HTTPS

╭────────────────────────────────────────────────────────────────────────────╮
│  Payload #1  ·  2 DNS · 1 HTTPS                                            │
├────────────────────────────────────────────────────────────────────────────┤
│  DNS  A                                                                    │
│  Query      4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com                     │
│  Resolvers  3.251.104.252, 3.251.104.34                                    │
│                                                                            │
│  HTTPS                                                                     │
│  Time      2026-09-27T21:25:04.333Z                                        │
│  Source    34.251.122.40:38382                                             │
│                                                                            │
│    GET / HTTP/1.1                                                          │
│    Host: 4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com                        │
│    Accept-Encoding: gzip                                                   │
╰────────────────────────────────────────────────────────────────────────────╯
```

Multiple DNS requests may be generated for a single OAST interaction because different DNS resolvers can query the same payload.

OAST-Community groups those callbacks together while preserving the individual resolver addresses.

### Listen for Interactions

Select:

```text
[3] Listen
```

The client continuously polls for new interactions:

```text
[2026-09-27T21:30:01Z] [*] Listening · polling every 5s
[2026-09-27T21:30:01Z] [*] Ctrl+C to return
```

New interactions are printed automatically when they arrive.

Press:

```text
Ctrl+C
```

to stop listening and return to the main menu.

### Browse Payloads

Select:

```text
[4] Payloads
```

Lists every payload generated under the current context, with its hit summary and any label or note:

```text
╭────────────────────────────────────────────────────────────────────────────╮
│  Payloads                                                                  │
├────────────────────────────────────────────────────────────────────────────┤
│  #1  4bgaemtqbl….oastify.com  · 2 DNS · 1 HTTPS  [login SSRF]              │
│  #2  ysumr9cb7v….oastify.com  · no hits                                    │
╰────────────────────────────────────────────────────────────────────────────╯
```

Enter a payload number to open its detail view. The detail view shows the
hostname (DNS / HTTP / HTTPS forms), creation time, and **every interaction
stored for that payload**, even ones received in a previous session.

From the detail view:

```text
[p] prefixed   Build a custom-data payload (see below)
[r] raw        Print the full raw request/response for every interaction
[s] save       Save a full plain-text report of this payload to a file
[d] resolve    Reverse-DNS lookup of every source address
[n] note       Attach a free-text note (e.g. the vulnerability under test)
[l] label      Attach a short label shown in the list
[b] back       Return to the payload list
```

Labels and notes are saved to the persistent context immediately.

### Raw Request / Response and Reports

`[r] raw` prints the complete decoded content of every stored interaction for
the payload: DNS query and type, full HTTP request **and** response, and the
full SMTP conversation.

`[s] save` writes the same report to a text file in the current directory, named
`oast-payload-<id>-<timestamp>.txt`, for use as evidence or in a report.

### Reverse DNS

`[d] resolve` performs a reverse-DNS (PTR) lookup for every source address seen
for the payload and prints the results:

```text
  9.9.9.9           dns9.quad9.net
  34.251.122.40     no PTR record
```

Lookups are cached for the session and bounded by `--timeout`.

## Custom-Data Payloads

A single payload can be reused in many injection points and still be told
apart, by prepending your own label to the hostname:

```text
login-ssrf.<id>.oastify.com
header-xff.<id>.oastify.com
param-url.<id>.oastify.com
```

The Collaborator server only looks at `<id>` to route the interaction, so the
prefix is free-form. When the target resolves or requests the name, the full
queried hostname is returned, and OAST-Community extracts the prefix and shows
it as a **Context** line:

```text
╭────────────────────────────────────────────────────────────────────────────╮
│  Payload #1  ·  2 DNS                                                      │
├────────────────────────────────────────────────────────────────────────────┤
│  Context    param-url                                                      │
│                                                                            │
│  DNS  A                                                                    │
│  Query      param-url.4bgaem….oastify.com                                  │
╰────────────────────────────────────────────────────────────────────────────╯
```

This is the same idea as Burp Collaborator's "payload with custom data": one
payload, many labelled uses, so a single callback tells you exactly which
injection point fired.

Build one from `[4] Payloads` → select a payload → `[p]`:

```text
Prefix (e.g. login-ssrf) > header-xff

[+] Prefixed payload (reuses this id)

  header-xff.4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com
  http://header-xff.4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com/
  https://header-xff.4bgaemtqblaca8gt3a62xdaf96fw3l.oastify.com/
```

Prefixes must be valid DNS labels (`a-z`, `0-9`, `-`, `.`) and are remembered
on the payload for reference. DNS resolvers may lowercase names, so prefixes
are normalized to lowercase.

## Persistent Interaction History

Polling consumes interactions on the Collaborator server, so each event is
returned only once. OAST-Community stores every received interaction in the
local context as it arrives (during both **Poll now** and **Listen**), mapped
to the payload that generated it.

This means interactions are not lost after a poll: they remain available under
`[4] Payloads` across restarts. Interactions whose payload is not in the local
context (for example, generated from another machine sharing the same server)
are kept as `orphan` records.

## Private Collaborator Server

By default the client uses the public `oastify.com` infrastructure, which is
shared. If you run your own private Burp Collaborator server, point the client
at it with a single flag:

```bash
python3 oast_community.py --server oob.example.com
```

This sets both the payload domain and the polling host to `oob.example.com`.
Override either independently if your server separates them:

```bash
python3 oast_community.py --server oob.example.com --poll-host poll.oob.example.com
```

A private server gives you an isolated namespace (no interactions from other
users), a domain of your own, and control over availability. State is stored
separately per server, so switching between the public and a private server
keeps independent payload histories.

## Supported Interaction Types

| Protocol | Details shown |
| --- | --- |
| DNS | record type, queried name, grouped resolver addresses |
| HTTP / HTTPS | time, source, full request (and response via `[r]` / `--debug`) |
| SMTP / SMTPS | time, source, `MAIL FROM`, `RCPT TO`, message, full conversation |

Any other protocol reported by the server is shown with its raw payload.

## Multiple Payloads

A single client context can generate multiple OAST payloads.

Example:

```text
Payload #1
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.oastify.com

Payload #2
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.oastify.com
```

Both payloads remain associated with the same client context.

The main menu shows the number of generated payloads and the most recently generated hostname:

```text
╭────────────────────────────────────────────────────────────╮
│  OAST Community  v1.0.0                                    │
├────────────────────────────────────────────────────────────┤
│  Payloads  2                                               │
│  Latest    bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.oastify.com      │
├────────────────────────────────────────────────────────────┤
│  [1] New payload                                           │
│  [2] Poll now                                              │
│  [3] Listen                                                │
│  [4] Payloads                                              │
│  [0] Exit                                                  │
╰────────────────────────────────────────────────────────────╯
```

Interactions are automatically mapped back to the payload that generated them.

## Persistent State

By default, OAST-Community saves the current client context under:

```text
~/.oast-community/
```

The state file contains the information required to retrieve interactions for previously generated payloads.

The state directory and files are locked down to the current user: `0700` / `0600`
on Unix-like systems, and on Windows the ACL is reset so that only the current
user account can read them. Treat the state as sensitive — it holds the secret
needed to retrieve your interactions.

This allows the client to be closed and reopened without losing the current context.

For example:

```bash
python3 oast_community.py
```

may restore:

```text
Payloads  2
Latest    bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.oastify.com
```

### Context Lifecycle

The `--context` flag controls how state is handled:

```bash
python3 oast_community.py --context persist      # default: reuse saved state
python3 oast_community.py --context new          # start a fresh context
python3 oast_community.py --context ephemeral    # no state read or written
```

A new context starts with:

```text
Payloads  0
Latest    none
```

An ephemeral context exists only for the lifetime of the process.

> The older `--new-context` and `--no-state` flags still work as aliases for
> `--context new` and `--context ephemeral`.

## Optional Flags

```text
--server <HOST>
    Private Collaborator server host.
    Sets both --domain and --poll-host unless they are
    given explicitly.

--domain <DOMAIN>
    Payload domain.
    Default: oastify.com

--poll-host <HOST>
    Collaborator polling host.
    Default: polling.oastify.com

--interval <SECONDS>
    Continuous listener polling interval.
    Default: 5

--timeout <SECONDS>
    Maximum network request time.
    Default: 15

--context {persist,new,ephemeral}
    Context lifecycle. persist (default) reuses saved
    state, new starts fresh, ephemeral uses no state.

--protocol <LIST>
    Comma-separated protocol filter for the poll action
    (e.g. dns,http,smtp).

--json
    Machine-readable JSON output for the new, poll and
    list actions.

--no-color
    Disable ANSI terminal colors.

--debug
    Enable additional diagnostic information.

--version
    Print the current OAST-Community version.
```

Example:

```bash
python3 oast_community.py --debug
```

Disable colors:

```bash
python3 oast_community.py --no-color
```

Check the installed version:

```bash
python3 oast_community.py --version
```

Example:

```text
OAST Community 1.4.0
```

## Non-Interactive Actions (Scripting)

Besides the interactive menu, OAST-Community accepts one-shot actions so it can
be used from scripts and pipelines, similar to a CLI OOB client:

```bash
python3 oast_community.py new     # generate one payload, print the hostname, exit
python3 oast_community.py poll    # poll once, print interactions, exit
python3 oast_community.py list    # list stored payloads, exit
```

Add `--json` for machine-readable output on any of them. In JSON mode, log
messages go to stderr so stdout contains only JSON:

```bash
# Capture a fresh payload in a shell variable
HOST=$(python3 oast_community.py new)

# Poll and pipe interactions into jq
python3 oast_community.py poll --json | jq '.[].source'

# Only DNS interactions
python3 oast_community.py poll --json --protocol dns
```

`new` with `--json` prints the hostname together with ready-to-use URLs:

```json
{
  "number": 1,
  "host": "abc….oastify.com",
  "dns": "abc….oastify.com",
  "http": "http://abc….oastify.com/",
  "https": "https://abc….oastify.com/"
}
```

These actions share the same persistent context as the interactive menu, so a
payload generated with `new` can be inspected later under `[4] Payloads`.

## How It Works

OAST testing is useful when a vulnerability cannot directly return its result to the tester.

Instead, the tested application is induced to interact with an external server controlled by the tester.

Typical interaction types include:

```text
DNS
HTTP
HTTPS
SMTP
```

OAST-Community creates a client context and generates unique interaction identifiers associated with that context.

A generated payload may then be inserted into an authorized security test, for example where an application performs a server-side request.

When the target resolves or requests the generated hostname, the interaction is recorded by the Collaborator infrastructure.

OAST-Community retrieves those interactions through polling and maps them back to the corresponding locally generated payload.

## Example Use Cases

OAST techniques are commonly useful when testing for vulnerabilities such as:

- Blind SSRF
- Blind command injection
- Blind XXE
- Server-side URL fetching
- Out-of-band data exfiltration in authorized environments
- DNS-based callback detection
- HTTP callback detection

The generated payload itself is intentionally displayed as a hostname:

```text
example.oastify.com
```

This allows the same payload to be reused in different protocols and contexts.

## Notes

- OAST-Community currently defaults to the public `oastify.com` Collaborator infrastructure.
- Public Collaborator infrastructure is operated by PortSwigger and may change independently of this project.
- Polling can consume interactions returned by the server, so retrieved events may not appear again on subsequent polls.
- DNS callbacks may involve multiple recursive resolvers for a single application action.
- HTTP and HTTPS callbacks are displayed separately when the Collaborator backend reports the protocol distinction.
- The local state should be treated as sensitive because it contains the client context required to retrieve interactions.
- Do not publish or commit files from `~/.oast-community/`.

## Project Structure

```text
OAST-Community/
├── LICENSE
├── README.md
├── requirements.txt
└── oast_community.py
```

## Legal

- OAST-Community is intended for **authorized security testing, educational environments, vulnerability research, and lab use**.

- Only use this software against systems you own or have explicit permission to test.

- The authors and contributors are not responsible for misuse or damage caused by this software.

- Burp Suite, Burp Collaborator, and PortSwigger are trademarks or products of their respective owners.

- This project is unofficial and is not affiliated with, sponsored by, or endorsed by PortSwigger.
