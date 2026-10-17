# Skirmesh-RF

Skirmesh-RF is the Atalaia field protocol. The same messages travel over LoRa, Wi-Fi, BLE, USB serial and the internet; only the encoding differs:

- **LoRa**: compact CBOR with integer keys, authenticated with a per-game key.
- **Wi-Fi, BLE, API**: JSON with readable keys.

Both encodings come from the schema files in [`schema/`](schema/), so they cannot drift apart.

| Path | Contents |
| --- | --- |
| [`schema/messages.yaml`](schema/messages.yaml) | Packet header and message types (draft) |
| [`schema/events.yaml`](schema/events.yaml) | Standard events: ids, priorities, CBOR keys and data fields (draft) |
| [`vectors/events.yaml`](vectors/events.yaml) | Test vectors every event codec must pass |
| [`json/event.schema.json`](json/event.schema.json) | JSON Schema of an event in the game log and the API (generated) |
| [`json/examples/`](json/examples/) | Events that CI validates against that schema, plus invalid ones it must reject |

## Changing the schema

1. Edit `schema/*.yaml`. Changes to standard events, protocol fields or keys need an RFC (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
2. Run `python3 tools/protogen.py` (it needs only PyYAML) and commit the generated files with the schema.
3. Run `tools/check.sh`. CI fails if a generated file is out of date.

The generator writes these files; none of them should be edited by hand:

| Generated file | For |
| --- | --- |
| `core/include/atalaia/protocol.h`, `core/src/protocol.c` | C: constants, ids, keys and lookup tables |
| `core/tests/protocol_vectors.h` | C: the test vectors |
| `simulator/atalaia_sim/protocol.py` | Python: the same tables |
| `protocol/json/event.schema.json` | Anyone consuming events as JSON |

Ids and keys are never reused once protocol v1 is frozen. Until then they may change.

## Events on LoRa

An EVENT message carries one event as a CBOR map with integer keys. The codecs are [`core/src/codec.c`](../core/src/codec.c) (C, used on every node) and [`simulator/atalaia_sim/codec.py`](../simulator/atalaia_sim/codec.py) (Python).

| Key | Field | Value |
| --- | --- | --- |
| 1 | `node` | Source node short id, 0 to 65535 |
| 2 | `seq` | Per-node sequence number, 0 to 65535 |
| 3 | `t` | Game time in milliseconds, 0 to 2³²−1 |
| 4 | `type` | A standard event's id, or the event name as text (custom events) |
| 5 | `team` | Team id, 1 to 250; left out for none |
| 6 | `squad` | Squad id, 1 to 255; left out for none |
| 7 | `prio` | 0 telemetry, 1 normal, 2 critical; left out when it is the event's default |
| 8 | `data` | The event data as a map; left out when empty |

In `data`, the names in `data_fields` become their integer key (`team` is 1, `reason` is 3, and so on), and every other key stays text. Values are what JSON can hold: integers that fit in 64 bits, finite floats, text, booleans, null, arrays and maps with text keys.

For example, red arming the bomb (`bomb.armed`, team 1, `{"fuse_s": 300, "team": "red"}`) takes 24 bytes:

```
a6                      map of 6
   01 01                node: 1
   02 01                seq: 1
   03 19 13 88          t: 5000
   04 07                type: bomb.armed (id 7)
   05 01                team: 1
   08 a2                data: map of 2
      07 19 01 2c          fuse_s: 300
      01 63 72 65 64       team: "red"
```

Encoders write integers, lengths and floats in their shortest form (a float uses half, single or double precision, whichever keeps its exact value). They keep map entries in the order of the input; the core writes data keys in sorted order. Decoders accept only this subset of CBOR and reject anything else:

- byte strings, tags, indefinite lengths, `undefined` and other simple values, NaN and infinity;
- invalid UTF-8, duplicate keys (a field sent both by key and by name counts as a duplicate), and trailing bytes;
- unknown envelope keys, event ids and data keys;
- data nested more than 16 levels deep, or more than 128 keys in the data maps open at once.

## Events as JSON

In the game log and on the API, an event is a JSON object with readable names. Nodes still use short ids on the field, and the field controller turns them into names:

```json
{
  "id": "box-a3f1:1842", "t": 734210, "node": "box-a3f1",
  "type": "code.used", "team": "blue", "squad": "blue-2",
  "data": { "code": "HINT-07", "kind": "hint" }, "prio": "normal"
}
```

[`json/event.schema.json`](json/event.schema.json) checks the envelope, that the type is standard or named `x.<club>.<name>`, and that a standard event carries only its own data fields (plus `team` and `squad`) with the right types.

## In the simulator

Mode tests fail when a script emits an event that is not in the schema, gives it a data field it does not have or a value of the wrong type, or produces a payload larger than the 200 bytes a LoRa packet can carry. Custom events (`x.<club>.<name>`) can carry any data, but still have to fit.

## Not defined yet

These arrive with the LoRa work in phase 2:

- the bit layout of the header's `version_flags` byte, and the byte order of header fields;
- the MIC (AES-CCM with the game key) and the key exchange during join;
- payloads of the other messages (HELLO, ACK, STATE, CMD, TIME, CONFIG, CLAIM);
- sending a team's name in `data.team` as well as its id in the envelope is redundant on LoRa. Dropping the name needs the receiver to know the game's teams, so it waits for the join flow.
