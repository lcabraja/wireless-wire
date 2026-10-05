# Turing 3.5-inch revision A

Adapter for the Turing/TURZX 320 × 480 USB serial display, USB ID `1a86:5722`.
Linux provides the `cdc_acm` transport. This adapter sends revision A commands
and RGB565 pixels, using only Python's standard library for serial I/O.

`0` and `180` select portrait; `90` and `270` select landscape. Partial rectangle
updates, bounded writes and an exclusive advisory device lock are supported.
The original 3.5-inch firmware may not answer HELLO and has no framebuffer
readback. Other display sizes/protocol revisions are not supported by this adapter.

This is the custom driver from the earlier monitor project. Protocol reference:
[Turing revision A](https://github.com/mathoudebine/turing-smart-screen-python/blob/main/library/lcd/lcd_comm_rev_a.py).
No vendor application, upstream driver package or firmware is bundled.
