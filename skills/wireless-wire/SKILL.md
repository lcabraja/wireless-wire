---
name: wireless-wire
description: Install, configure or troubleshoot Wireless Wire, an iPhone usbmux service bridge over Tailscale between a Linux USB host and a Mac or Linux client. Use for this project and its releases, not generic USB/IP, Android, or Finder integration.
---

# Wireless Wire

Use https://github.com/lcabraja/wireless-wire and its versioned releases.
Determine which authorized machine physically hosts the iPhone and which machine
is the client. The Linux host needs USB host mode, Python 3.11+, usbmuxd and
Tailscale. The Mac client needs Python 3.11+ and Tailscale. Never guess an SSH
username, key or destination from an example.

Read the release README for the supported setup. Release launchers require the
adjacent `wireless-wire.pyz` and a separately installed Python. Verify release
checksums before installation. Source checkouts build with `python3 scripts/build.py`.

- On the Linux USB host, run `sudo bash scripts/install-server.sh --listen HOST_TAILSCALE_IP`.
- Privately transfer `/etc/wireless-wire/token` over the authorized SSH connection.
  Do not print it, pass it on a command line, or put it in this repository. Keep
  copies mode 0600. Do not print pairing records or device identifiers in reports.
- On a Mac client, run `python3 scripts/install-client.py --remote HOST_TAILSCALE_IP:48200 --token-file PRIVATE_FILE`.
  The installer keeps a private copy and creates `org.wireless-wire.client`.
- A Linux client can run `python3 wireless-wire.pyz bridge` with the same remote
  and token options. The client listens only on localhost:27015.

Verify `wireless-wire.service` is active on the host and use `doctor --side mac`
on the client. An empty device list can be healthy before an iPhone is attached.
For a hardware test, attach the unlocked iPhone to the Linux host and accept Trust.
Then use `doctor --side mac --require-device` and `run -- ideviceinfo -k ProductVersion`.
If pairing needs attention, run `idevicepair pair` through `run` and have the user
accept Trust. Capture diagnostic output privately and report only success/failure
and non-identifying fields. Do not claim end-to-end success from listening sockets alone.

The transport relies on Tailscale encryption; accepting a CGNAT address is not
proof of VPN routing. Keep the service on its actual Tailscale IP and honor tailnet
access rules. Any local process can access the client's usbmux socket. Existing
streams end when connectivity drops; the next connection retries naturally.

Check USB enumeration and usbmuxd on the host if no device appears. Check the
client service, remote address, token permissions and Tailscale reachability if
the local socket cannot list devices. Use service logs without exposing secrets.
Preserve pairing records and existing tokens during upgrades. Do not reflash
storage or change authentication settings as a routine troubleshooting step.

This is an iPhone service bridge, not arbitrary USB redirection. Finder/Xcode,
Android and storage-device support are outside v1. No third-party adapter is
bundled. State this boundary when the requested workflow depends on those features.
