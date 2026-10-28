# The I/O pod's settings over the radio (CMD pod, opcode 10)

Until now an I/O pod's settings (the colours of its buttons, the ring's brightness, the volume, whether its enclosure switch reports) were the firmware build's Kconfig, fixed when the image was made ([capability-proxy.md](capability-proxy.md), plan phase F, decision PF15). Now the field controller can push them to a pod over Skirmesh-RF, from the GM console (Pi or phone controller), before a game starts. This file is the specification. It is **additive** and **versioned**: it adds one CMD opcode (RFC 0001 Amendment 17) and changes no frame, no field and no opcode that exists; a pod or a box that does not know it ignores it, and a controller that never sends it changes nothing.

Shared vectors: [`vectors/pod_config.json`](vectors/pod_config.json) (written by `tools/pod_config_vectors.py`), checked by the pod's C (`firmware/esp32/main/pod/pod_settings.c`: `firmware/esp32/test/test_pod_settings.c`, through the generated `pod_config_vectors.h`), the Pi controller (`controller/atalaia_controller/pod_config.py`: `controller/tests/test_pod_config.py`) and the Android controller (`app/lib/controller/controller_pod_config.dart`: `app/test/controller/controller_pod_config_test.dart`).

## 1. The command

CMD opcode **10** (`pod`), an ordinary sealed game packet ([RFC 0001](../docs/rfcs/0001-skirmesh-rf-wire-format.md): AES-128-CCM with the game key, the epoch and nonce rules, critical priority, ACK requested, flooded like every CMD). The payload is the CMD map of the wire format: key 1 the opcode (10), key 2 `params`, key 3 `dest`.

- **`dest`** is the **node id of the phone the pod serves**, the id the phone has in the game (the pod's radio is that node's radio: the phone gave the pod its game id, node id and key with RADIO_CMD CONFIGURE). A command to every node (65535, no `dest`) is never a pod's: the pod ignores it, and the controllers never send one.
- **`params`** is a map with text keys whose compact JSON form fits the CMD's 127 bytes:

| Key | Type | Meaning |
| --- | --- | --- |
| `v` | uint | the format's version, **1**; required. A pod ignores a higher one (it does not guess at it). |
| `rev` | uint, 1 to 2^32-1 | the controller's count of pushes to this pod; required. See "Revisions". |
| `reset` | bool | `true` first drops every setting pushed so far: the build's Kconfig values are back. Optional. |
| `btn` | array of exactly 4 text | the colour of buttons 1 to 4: `""` (the game's N-th team, as a Field Box's button N) or one of `red`, `blue`, `green`, `yellow`, `orange`, `purple`, `white`, `pink`, `cyan`. It goes into the button's descriptor in the pod's IDENT. Optional. |
| `bright` | uint, 0-100 | the LED ring's default brightness in percent (what `set_brightness` changes during a game). Optional. |
| `vol` | uint, 0-100 | the volume in percent. Optional. |
| `tamper` | bool | whether the enclosure switch reports (`case` capability). `false` silences a switch; `true` never turns on a switch the build did not fit (`CONFIG_ATALAIA_POD_TAMPER_PIN` -1). Optional. |

The pod **refuses the whole command, applying nothing**, for a key it does not know (this version's keys are the ones above), a repeated key, a value of the wrong type or out of range (a fraction, a negative number, 101 percent, a colour it has no name for, `btn` with other than four entries), a missing `v` or `rev`, `rev` 0, or a `v` other than 1. Only the settings given change; the rest keep their last value (or the build's). The shared vectors list every one of these cases.

**What is not here, on purpose** (decision PODC-2): the game key, the radio's region and channel, the pins, the Bluetooth security (`CONFIG_ATALAIA_POD_BLE_ENCRYPTED`), and the **admin PIN and LED count** that ADR-P3-3 mentioned. A pod has no admin menu and no screen, so it has no admin PIN to set; the ring's LED count and every pin are wiring facts that stay in the build's Kconfig (`docs/manuals`, the I/O pod build guide), because a count the wiring does not match is a pod that lights the wrong LEDs and a wrong pin can drive another part's output. Settings that change what an unattended pod does to the radio or to its own security are not for a radio command.

## 2. What the pod does

The pod's radio is the USB modem's logic ([usb-modem.md](usb-modem.md)): it opens every packet of the configured game with the game key, drops repeats, and passes the plaintext to its phone as RADIO_RX. With this feature it looks at each packet **after** that authentication and the repeat check: a CMD with opcode 10 whose `dest` is the node id the radio was configured with is **taken by the pod and not passed on** (a pod without this feature passes it on like any packet, and the phone ignores an opcode it does not know). So the command is **authenticated like every other CMD**: sealed with the game key, in an epoch the pod accepts, not a repeat. A packet sealed with another key, in another game, or repeated is dropped by the modem's own checks before the pod sees it.

The pod then:

1. parses the params (section 1) and decides by `rev`;
2. **applied** (`rev` above the last it took): merges the settings, writes them to its flash (NVS namespace `pod`, key `settings`, the same JSON with the last `rev`; read back at boot and applied before the first IDENT), puts them on the buttons' descriptors, the ring, the sound and the switch, sends its **IDENT again** on every active link (the buttons' colours changed) and sends the EVT below;
3. **same** (`rev` equal to the last it took, a repeat of a command it already took: the controller sent it again because the answer was lost): applies nothing, and sends the EVT again;
4. **stale** (`rev` below the last) or **refused** (invalid, or a newer `v`): ignores it, says nothing on the air, and counts it (`config_ignored`; a line in the log).

### Revisions

A pod keeps the last `rev` it took in its flash. A controller must therefore send a `rev` above it, whichever controller (or whichever run of the same controller) sent the last one. Both controllers use **the wall clock's seconds since 1970, or one more than the last `rev` they sent to that node if that is higher**: it needs no storage in the controller (a restarted one is still above) and fits 32 bits until 2106. The GM may give an explicit `rev` in the API's body to start over (for a pod whose stored `rev` came from a clock that was wrong). A pod's `rev` is per pod, not per game.

## 3. The acknowledgement

The pod has no node id of its own on the air: its packets are its phone's. So the pod's answer takes the way the pod's other events take, and then the way a **box's setup acknowledgement** takes (RFC 0001 Amendment 16, `node.setup_applied`, decision PKB):

1. The pod sends an **EVT** to its phone ([capability-proxy.md](capability-proxy.md)): capability `pod`, event `config`, data `{"rev": N}`. It has the proxy's own ACK and resends (500 ms, 3 times). It is sent on every active link; with no link active the event is dropped (the phone is not there; the controller will send the command again).
2. The phone (the app's prop session, `app/lib/prop/prop_session.dart`) turns it into the standard event **`node.setup_applied`** (id 56, normal priority) with data `{"kind": "pod_config", "rev": N}` and sends it over the field's radio, as any event: the radio's ACK and resend rules carry it to the controller. (`kind` is the setup's kind; `rev` is an extra key, which events allow.)
3. The controller matches the event to its push by node and `rev` and shows the pod's settings as **taken**.

Until then the controller sends the command again after **8, 16, 32, 64 and 128 seconds** (the first sending and five repeats, the same waits as a scenario's setup), each repeat a new packet with the same `rev` and settings, then it says the pod **did not answer**. A late answer is still taken. The reasons for no answer, which the console lists: the phone has no I/O pod (the controller cannot tell: the HELLO of a phone does not say), the pod's firmware is older than this feature, the pod is out of radio reach or not linked (no active link), the `rev` was already passed (stale), or the command was refused as invalid (the controllers check it first, so this is a controller older than the pod).

## 4. When, and who

Only **before a game starts or after it ended** (`ready`, `ended`): a button that changes colour in the middle of a game is the players' surprise, and every push costs airtime (critical priority, flooded). It is the GM's alone: GM token (the Pi's `POST /api/v1/pod-config/{node}`), never a mode's `field.lua` (`field.send(node, "pod", ...)` is refused). It is never broadcast.

The controllers list the phones of the live game (HELLO `platform` 3) as the candidates; whether one has a pod is not in its HELLO, and the answer tells.

## 5. Threat model

- **Who can send it:** anyone holding the game key can seal any CMD, as for every command (the boxes' `reset` and `reboot` too): the key is shared by the field's props and controllers, and per-node keys are an open question of RFC 0001. The pod adds no weaker path: no key, wrong epoch or a repeat never reach it.
- **What the worst command can do:** change colours and levels, silence the enclosure switch (the one with a security meaning), or write the same few bytes to flash again. It cannot change the radio, the pins, the key or the pairing, cannot brick the pod (a damaged stored form reads back as no settings: the build's values), and cannot be made to fill the flash (one small string, written only when a new `rev` is taken). `tamper: false` hides a lid opening from the GM, which is why only a holder of the game key can do it: the same trust every other event and command already needs.
- **Replays:** an old packet is dropped by the modem's dedupe and epoch window; an old command resent in a new packet (a recorded `rev` 5 sent at `rev` 9) is stale and ignored.
- **Wear:** each applied push writes the flash once; pushes are the GM's, before a game.

## 6. Compatibility

An older **pod** passes the CMD to its phone as a packet (the phone's radio link ignores an opcode it does not know, `cmd_10`) and never answers: the controller's "no answer". An older **box** meeting the opcode (a CMD to every node is never sent, but a pod's `dest` is a phone's id) logs "unknown command ignored". An older **controller** never sends it. An older **phone** app passes a pod's EVT it does not know as an input it does not map: the pod's settings are taken, the controller is never told (no answer, though applied). The IDENT, EVT and CMD frames of the proxy and every other opcode are unchanged; `protocol_version` stays 1.
