// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Which addresses the check-in poster lists and the server certificate
/// covers (decisions check-R8, check-R9): controller/atalaia_controller/
/// addresses.py, rule for rule, and the shared cases of
/// protocol/vectors/checkin.json ("poster_addresses").
///
/// The poster lists only configured *names* and addresses that are on an
/// interface *now*. A configured address that is on no interface is left out
/// and warned about; a host name cannot be checked, so it stays. The phone has
/// no `[api] tls_names`: what it has is [found] (its addresses now, best
/// first, from [localAddresses]), the saved poster's urls and `config.urls`.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

/// What the poster, the join payloads and the certificate get from one look at
/// the addresses.
class AddressPlan {
  const AddressPlan({
    required this.defaultUrls,
    required this.explicit,
    required this.poster,
    required this.san,
    required this.dropped,
  });

  /// https urls: the configured names, then what was found (at most 3).
  final List<String> defaultUrls;

  /// The GM's urls that survived (empty: none given, or none survived).
  final List<String> explicit;

  /// What the poster lists: [explicit], else [defaultUrls].
  final List<String> poster;

  /// The certificate's names: a superset of the poster's hosts.
  final List<String> san;

  /// Configured addresses left out because they are on no interface.
  final List<String> dropped;
}

final _hostRe = RegExp(r'^https://(\[[^\]]+\]|[^:/]+)(?::\d+)?');
final _containerId = RegExp(r'^([0-9a-f]{12}|[0-9a-f]{64})$');

/// The host of an https base url, without the brackets of an IPv6 one ('' if
/// it is not one).
String urlHost(String url) {
  final m = _hostRe.firstMatch(url);
  if (m == null) return '';
  final h = m.group(1)!;
  return h.startsWith('[') ? h.substring(1, h.length - 1) : h;
}

/// A comparable form of an IP address, or null for a name.
String? _ipKey(String name) {
  var n = name.trim();
  if (n.startsWith('[') && n.endsWith(']')) n = n.substring(1, n.length - 1);
  final a = InternetAddress.tryParse(n);
  if (a == null) return null;
  return '${a.type.name}:${a.rawAddress.join('.')}';
}

bool _unspecified(Uint8List raw) => raw.every((b) => b == 0);

/// `tls.link_names`: the names and addresses given to boxes and phones,
/// best first: the configured ones, then the ones found that another device
/// can use (not loopback, link-local or unspecified addresses, `localhost`, a
/// host name shaped like a container id), and none of those in a container.
List<String> linkNames(
  List<String> configured,
  List<String> found, {
  bool container = false,
}) {
  bool reachable(String n, bool wasFound) {
    final ip = InternetAddress.tryParse(n.replaceAll(RegExp(r'^\[|\]$'), ''));
    if (ip == null) {
      final host = n.endsWith('.local')
          ? n.substring(0, n.length - '.local'.length)
          : n;
      return n != 'localhost' && !(wasFound && _containerId.hasMatch(host));
    }
    return !(ip.isLoopback ||
        _unspecified(ip.rawAddress) ||
        (wasFound && ip.isLinkLocal));
  }

  final out = <String>[];
  for (final raw in configured) {
    final n = raw.trim();
    if (n.isNotEmpty && !out.contains(n) && reachable(n, false)) out.add(n);
  }
  if (!container) {
    for (final n in found) {
      if (n.isNotEmpty && !out.contains(n) && reachable(n, true)) out.add(n);
    }
  }
  return out;
}

/// The addresses this device has now, and the rules above applied to them.
class FieldAddresses {
  FieldAddresses({
    this.tlsNames = const [],
    this.found = const [],
    this.interfaces = const [],
    this.tlsPort = 8443,
    this.container = false,
    this.filterFound = true,
  }) : _ips = {
         for (final n in [...interfaces, ...found])
           if (_ipKey(n) != null) _ipKey(n)!,
       };

  final List<String> tlsNames;

  /// The names and addresses found now, best first.
  final List<String> found;

  /// The IP addresses on an interface now (what was found counts too).
  final List<String> interfaces;
  final int tlsPort;
  final bool container;

  /// False: [found] is listed as it is. The phone's [localAddresses] has left
  /// out loopback, link-local and mobile-data addresses already, and a test
  /// controller on 127.0.0.1 must list it; the Pi's `tls.link_names` filters
  /// what it finds (the shared cases run with true).
  final bool filterFound;
  final Set<String> _ips;

  /// A name always (it cannot be checked); an address if it is on an
  /// interface now, or in a container, where that cannot be known.
  bool currentHost(String host) {
    final k = _ipKey(host);
    return k == null || container || _ips.contains(k);
  }

  String _url(String name) {
    final host = name.contains(':') ? '[$name]' : name;
    return tlsPort != 443 ? 'https://$host:$tlsPort' : 'https://$host';
  }

  /// (the urls whose host is current, at most 3; the ones left out).
  (List<String>, List<String>) keep(Iterable<String> urls) {
    final kept = <String>[];
    final dropped = <String>[];
    for (final u in urls) {
      if (currentHost(urlHost(u))) {
        if (!kept.contains(u)) kept.add(u);
      } else if (!dropped.contains(u)) {
        dropped.add(u);
      }
    }
    return (kept.take(3).toList(), dropped);
  }

  AddressPlan plan({
    Iterable<String> saved = const [],
    Iterable<String> checkinUrls = const [],
  }) {
    final (savedKept, d1) = keep(saved);
    final (configKept, d2) = keep(checkinUrls); // both: every stale one named
    final dropped = [
      ...d1,
      for (final d in d2)
        if (!d1.contains(d)) d,
    ];
    final explicit = savedKept.isNotEmpty ? savedKept : configKept;
    final names = <String>[];
    for (final raw in tlsNames) {
      final n = raw.trim();
      if (n.isEmpty) continue;
      if (currentHost(n)) {
        names.add(n);
      } else if (!dropped.contains(n)) {
        dropped.add(n);
      }
    }
    final defaults = <String>[];
    final listed = filterFound
        ? linkNames(names, found, container: container)
        : [
            ...names,
            for (final n in found)
              if (!names.contains(n)) n,
          ];
    for (final n in listed) {
      final u = _url(n);
      if (!defaults.contains(u) && u.length <= 64) defaults.add(u);
    }
    final def = defaults.take(3).toList();
    final san = <String>['localhost', '127.0.0.1'];
    for (final n in [
      ...names,
      for (final u in explicit) urlHost(u),
      ...found,
    ]) {
      final t = n.trim();
      if (t.isNotEmpty && t != '0.0.0.0' && !san.contains(t)) san.add(t);
    }
    return AddressPlan(
      defaultUrls: def,
      explicit: explicit,
      poster: explicit.isNotEmpty ? explicit : def,
      san: san,
      dropped: dropped,
    );
  }
}

/// The urls of the saved poster (the `checkin.poster` setting, JSON text), as
/// the GM saved them.
List<String> savedPosterUrls(String? raw) {
  if (raw == null) return const [];
  try {
    final m = jsonDecode(raw);
    final u = m is Map ? m['urls'] : null;
    return u is List
        ? [
            for (final x in u)
              if (x is String) x,
          ]
        : const [];
  } on FormatException {
    return const [];
  }
}
