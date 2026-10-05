"""Render the status dashboard to an RGB Pillow image; no USB access."""
from PIL import Image, ImageDraw, ImageFont

from common import clean


def render(state, size=(480, 320)):
    width, height = size
    portrait = width < height
    image = Image.new("RGB", (width, height), "#0b1320")
    draw = ImageDraw.Draw(image)
    white, muted, green, amber = "#eff5fc", "#91a6be", "#69e6b1", "#ffc477"

    def text(x, y, value, size=24, color=white, bold=False, available=None, lines=1):
        available = width - x - 22 if available is None else available
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans" + ("-Bold" if bold else "") + ".ttf"
        font = ImageFont.truetype(path, size)
        value = clean(value)
        for line in range(lines):
            if draw.textlength(value, font=font) <= available:
                draw.text((x, y), value, font=font, fill=color)
                break
            if line == lines - 1:
                while draw.textlength(value + "…", font=font) > available and value:
                    value = value[:-1]
                draw.text((x, y), value + "…", font=font, fill=color)
                break
            cut = len(value)
            while cut > 1 and draw.textlength(value[:cut], font=font) > available:
                cut -= 1
            space = value.rfind(" ", 0, cut + 1)
            if space > 0:
                cut = space
            draw.text((x, y), value[:cut], font=font, fill=color)
            value = value[cut:].lstrip()
            y += size + 6

    text(22, 14, "WIRELESS WIRE", 17, bold=True)
    draw.line((22, 47, width - 22, 47), fill="#263647")
    text(22, 56, "WI-FI", 11, muted, bold=True)
    text(width - 110, 56, "TAILSCALE", 11, muted, bold=True)
    text(22, 75, state["wifi"], 23 if portrait else 25,
         available=width - 154)
    text(width - 110, 81, "ONLINE" if state["tailnet"] else "OFFLINE", 13,
         green if state["tailnet"] else amber)
    lan = ", ".join(state.get("lan_ips", [])) or "No address"
    tail_ip = state.get("tailnet_ip") or "No address"
    text(22, 107, "LAN " + lan, 12, muted, available=width - 44 if portrait else 205)
    text(22 if portrait else 240, 126 if portrait else 107, "TS " + tail_ip, 12, muted)

    usb_y, client_y = (165, 282) if portrait else (137, 219)
    for y, label in ((usb_y, "USB DEVICE"), (client_y, "BRIDGE CLIENT")):
        draw.line((22, y - 7, width - 22, y - 7), fill="#263647")
        text(22, y, label, 11, muted, bold=True)
    text(22, usb_y + 19, ", ".join(state["usb"]) if state["usb"] else "Not connected",
         23 if portrait else 22, green if state["usb"] else amber)
    usb_info = [f'Port {d["port"]} / {d["speed"]}' for d in state.get("usb_details", [])]
    text(22, usb_y + 51, "; ".join(usb_info) or "No USB data link", 13, muted,
         lines=2 if portrait else 1)

    if state["clients"]:
        name = ", ".join(state["clients"])
        ips = ", ".join(state.get("client_ips", []))
        detail = f'{state["sessions"]} authenticated session(s)'
        color = green
    elif state["last_client"] and state["bridge"]:
        name = "Last: " + state["last_client"]
        ips = state.get("last_ip") or ""
        detail = "Disconnected / waiting for client"
        color = amber
    else:
        name = "Waiting for a client" if state["bridge"] else "Bridge unavailable"
        ips = ""
        detail = "0 authenticated sessions" if state["bridge"] else "Check wireless-wire service"
        color = amber
    text(22, client_y + 19, name, 22 if portrait else 20, color, lines=2 if portrait else 1)
    text(22, client_y + (82 if portrait else 46), ips, 13, muted)
    text(22, client_y + (106 if portrait else 66), detail, 12, muted,
         lines=2 if portrait else 1)
    return image
