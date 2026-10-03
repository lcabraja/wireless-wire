# v1 review

Reviewed the Python relay, command execution, installers, native launcher and
release packaging before the initial public commit.

- Authentication precedes every connection to the USB daemon. Token comparison
  is constant-time; token files reject symlinks, FIFOs, loose permissions,
  non-ASCII characters, control characters and oversized values.
- Handshakes have a size limit and deadline. Malformed JSON and plist messages
  become protocol errors. Remote error text is not passed through to logs.
- Connections use bounded buffering, preserve half-close, limit concurrency and
  cancel both directions on failure. Restarting does not replay stale sessions.
- The client listens on IPv4 loopback. Server addresses must be loopback or in
  Tailscale's address ranges. Encryption depends on Tailscale or an SSH tunnel;
  an address-range check is not proof of VPN transport.
- The shared token authorizes access to usbmuxd, including pairing records.
  Local processes can access the client socket. Use trusted client accounts and
  restrictive tailnet access rules. This is not a per-device authorization layer.
- Installers preserve existing pairing records. Credentials and runtime state
  stay outside the checkout. Mac updates replace managed files atomically.

Validation includes 24 automated tests for authentication, malformed input,
parallel binary transfers, half-close, connection limits, replug, reconnect,
service forwarding and a simulated slow link. The native macOS ARM64 and Linux
ARM64 launchers and the packaged app were exercised. The Linux build and tests
ran in a Debian Bookworm ARM64 container. Both the macOS installer and Linux
systemd installer were exercised. After publication, the unchanged v1.0.0
archive was installed on a Raspberry Pi 4; its service was enabled and active,
and the installed Mac client successfully queried the remote USB daemon. No
iPhone was attached during this post-release check.
The macOS archive also includes an x86_64 launcher slice.

An iPhone attached to a Raspberry Pi 4 was paired and queried from a remote Mac
over Tailscale. This does not establish support for Finder, Xcode, restore/DFU,
arbitrary USB devices, cellular performance or every iOS service.

The repository and release archives were checked for credentials, private keys,
pairing records, private network identifiers, personal paths and build metadata.
Source files identify the public project owner only in project URLs. Git uses
the public account name and GitHub noreply email. Releases contain this
project's code and launchers, not Python, Tailscale, usbmuxd, libimobiledevice or
the separate usbfluxd adapter. See DEPENDENCIES.md for separately installed tools.

This was a source review and functional test, not an independent security audit.
