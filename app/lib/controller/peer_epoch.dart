// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// When a controller names a box's epoch to the other receivers (RFC 0001
/// Amendment 24, decision SR-110): the Dart port of
/// simulator/atalaia_sim/peer_epoch.py, both passing
/// protocol/vectors/peer_epoch.json.
///
/// A box whose epoch store was lost sends at a random epoch in 4096..61439
/// (Amendment 23, SR-27), and a box that rebooted a few times sends a little
/// above where it was. Receivers follow a source only within a window of
/// epochs above the last they heard, so the controller, which hears the box,
/// tells its modem (SET_PEER_EPOCH) and every box (CMD peer, opcode 11, params
/// {src, epoch}, which a box applies only upwards). An announcement can never
/// move an epoch backwards: the rule needs the heard epoch above the known
/// one, a source is announced again only above the last announced epoch, and
/// the receivers refuse a lower one themselves.
library;

/// The window above a source's epoch that a receiver follows for any packet.
const peerEpochWindow = 16;

/// The announcement is sent again this long after the first (milliseconds).
const peerEpochRepeatAfterMs = [4000, 10000];

/// CMD peer's opcode: the controller's own, not in the GM's command list.
const cmdPeerEpoch = 11;

/// Is a packet of type [isHello] heard at epoch [heard] from a source last
/// known at [prior] (0: not heard before) worth an announcement? Only an epoch
/// above the known one ever is: a jump past the window, or a step up said by a
/// box already known (a HELLO: it has restarted).
bool shouldAnnouncePeerEpoch(int prior, int heard, {required bool isHello}) {
  if (heard <= prior || heard <= 0) return false;
  return heard - prior > peerEpochWindow || (isHello && prior > 0);
}

/// What a controller has announced, and the repeats that are due.
class PeerEpochs {
  final _sent = <int, int>{}; // source -> the highest epoch announced
  final _repeats = <int, (int, List<int>)>{}; // source -> (epoch, times due)

  /// A packet from [source] authenticated at epoch [heard]: true when it is to
  /// be announced now (the caller sends it and tells its modem); the repeats
  /// are scheduled.
  bool heard(int source, int prior, int heard, bool isHello, int nowMs) {
    if (!shouldAnnouncePeerEpoch(prior, heard, isHello: isHello)) return false;
    if (heard <= (_sent[source] ?? 0)) return false;
    _sent[source] = heard;
    _repeats[source] = (
      heard,
      [for (final g in peerEpochRepeatAfterMs) nowMs + g],
    );
    return true;
  }

  /// The (source, epoch) announcements to send again at [nowMs], each at most
  /// once per call (a late tick sends one, not a burst).
  List<(int, int)> due(int nowMs) {
    final out = <(int, int)>[];
    for (final source in _repeats.keys.toList()..sort()) {
      final (epoch, times) = _repeats[source]!;
      if (times.isNotEmpty && nowMs >= times.first) {
        times.removeWhere((t) => t <= nowMs);
        out.add((source, epoch));
      }
      if (times.isEmpty) _repeats.remove(source);
    }
    return out;
  }

  void forget() {
    _sent.clear();
    _repeats.clear();
  }
}
