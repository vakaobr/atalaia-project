// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Links into online registration (lib/site/site_link.dart): the site
// server's `atalaia://register` button and pasted page addresses.

import 'package:atalaia_app/site/site_link.dart';
import 'package:flutter_test/flutter_test.dart';

const game = '0192f3a0-0000-7000-8000-000000000001';

void main() {
  final site = Uri.parse('https://campo.example.pt');

  test('the register button\'s app link', () {
    final l = SiteGameLink.parse(
      'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-norte&game=$game',
    );
    expect(l, SiteGameLink(site, 'campo-norte', game));
    expect(l!.host, 'campo.example.pt');
    expect(SiteGameLink.parse(l.toAppLink().toString()), l);
  });

  test('pasted game, register and field pages, with a query and a port', () {
    expect(
      SiteGameLink.parse('https://campo.example.pt/f/campo-norte/games/$game'),
      SiteGameLink(site, 'campo-norte', game),
    );
    expect(
      SiteGameLink.parse(
        ' https://campo.example.pt/f/campo-norte/games/${game.toUpperCase()}/register?lang=en ',
      ),
      SiteGameLink(site, 'campo-norte', game),
    );
    final f = SiteGameLink.parse(
      'https://campo.example.pt:8443/f/campo-norte/',
    );
    expect(f!.gameId, isNull);
    expect(f.host, 'campo.example.pt:8443');
    expect(f.site.toString(), 'https://campo.example.pt:8443');
  });

  test('plain http only on this phone or the emulator\'s host', () {
    expect(
      SiteGameLink.parse('http://10.0.2.2:8000/f/campo-norte')!.site.toString(),
      'http://10.0.2.2:8000',
    );
    expect(SiteGameLink.parse('http://localhost/f/x'), isNotNull);
    expect(SiteGameLink.parse('http://campo.example.pt/f/campo-norte'), isNull);
    expect(
      SiteGameLink.parse(
        'atalaia://register?site=http%3A%2F%2Fevil.example&field=a',
      ),
      isNull,
    );
  });

  test('anything else is refused', () {
    for (final bad in [
      '',
      'atalaia:checkin:abc',
      'atalaia://join?site=https%3A%2F%2Fcampo.example.pt&field=a',
      'atalaia://register?field=campo',
      'atalaia://register?site=https%3A%2F%2Fcampo.example.pt%2Fpath&field=a',
      'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=Campo',
      'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=a&game=1',
      'https://campo.example.pt/',
      'https://campo.example.pt/f/campo/games',
      'https://campo.example.pt/f/campo/games/$game.ics',
      'https://campo.example.pt/f/campo/games/$game/other',
      'https://user:pw@campo.example.pt/f/campo',
      'ftp://campo.example.pt/f/campo',
      'https://campo.example.pt/x/campo',
    ]) {
      expect(SiteGameLink.parse(bad), isNull, reason: bad);
    }
  });

  test('a site address typed by hand', () {
    expect(parseSiteAddress('campo.example.pt')!.toString(), site.toString());
    expect(parseSiteAddress('https://campo.example.pt/f/x')!.path, '');
    expect(parseSiteAddress('http://campo.example.pt'), isNull);
    expect(parseSiteAddress(' '), isNull);
  });
}
