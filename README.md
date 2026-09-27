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
6. Displays complete HTTP and HTTPS requests received by the OAST server.
7. Provides a continuous listener mode for real-time interaction monitoring.
8. Persists the client context between executions.
9. Supports ephemeral sessions when persistence is not desired.
10. Uses only the Python standard library.

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

On Unix-like systems, the directory and state files are created with restrictive permissions.

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

### Create a New Context

To replace the current persistent context with a new one:

```bash
python3 oast_community.py --new-context
```

The new context starts with:

```text
Payloads  0
Latest    none
```

### Ephemeral Context

To create a temporary context without reading or writing state:

```bash
python3 oast_community.py --no-state
```

The context exists only for the lifetime of the process.

## Optional Flags

```text
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

--new-context
    Replace the current persistent client context with a new one.

--no-state
    Run with an ephemeral context and disable state persistence.

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
OAST Community 1.0.0
```

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
