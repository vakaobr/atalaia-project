# Skirmesh-RF

Skirmesh-RF is the Atalaia field protocol. The same messages travel over LoRa, Wi-Fi, BLE, USB serial and the internet; only the encoding differs:

- **LoRa**: compact CBOR with integer keys, authenticated with a per-game key.
- **Wi-Fi, BLE, API**: JSON with readable keys.

Both encodings are generated from the schema files in [`schema/`](schema/), so they can never drift apart.

| File | Contents |
| --- | --- |
| [`schema/messages.yaml`](schema/messages.yaml) | Packet header and message types (draft) |
| [`schema/events.yaml`](schema/events.yaml) | Standard game and system events (draft) |

Changes to these files need an RFC (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
