# Licensing

Atalaia uses copyleft licences: anyone may use, study, modify and even sell Atalaia, including fields that charge entry fees and makers who sell pre-built props. In return, anyone who **distributes** a modified version, or **runs a modified controller or site server for others over a network**, must publish their changes under the same licence. Improvements flow back to the community.

| Part | Folders | Licence (SPDX) |
| --- | --- | --- |
| Core, protocol, firmware, modes, simulator, tools | `core/`, `protocol/`, `firmware/`, `modes/`, `simulator/`, `tools/` | `GPL-3.0-or-later` |
| App (Android and iOS) | `app/` | `GPL-3.0-or-later`, plus the [app-store permission](app/APP-STORE-PERMISSION.md) |
| Field controller | `controller/` (except the console) | `AGPL-3.0-or-later` |
| GM console | `controller/console/` | `GPL-3.0-or-later`, plus the [app-store permission](app/APP-STORE-PERMISSION.md) |
| Site server | `server/` | `AGPL-3.0-or-later` |
| Hardware designs | `hardware/` | `CERN-OHL-S-2.0` |
| Documentation and the project page | `docs/`, `site/` | `CC-BY-SA-4.0` |

The GM console was AGPL-3.0-or-later until 2026-10-22. It is browser code that every user's browser receives as readable source, so the AGPL's network clause added nothing to it, and the app could not ship it with the app-store permission under the AGPL. Its copyright holder moved it to GPL-3.0-or-later with that permission, so the phone controller can serve the same console (decision PE24-8); the controller's server code stays AGPL-3.0-or-later.

Full licence texts are in [`LICENSES/`](LICENSES/). The root [`LICENSE`](LICENSE) file holds the GPL text because it covers most of the repository. Per-folder licences are declared in [`REUSE.toml`](REUSE.toml), following the [REUSE](https://reuse.software) conventions, and source files carry `SPDX-License-Identifier` headers.

## Third-party code

Third-party components keep their own licences and must be compatible with GPL-3.0. The project page bundles the Barlow and Barlow Condensed fonts (OFL-1.1) in `site/fonts/`. The ESP32 firmware uses LVGL (MIT), downloaded at build time; its configuration file `firmware/esp32/lvgl_conf/lv_conf.h` is LVGL's MIT template. The firmware's screen tests vendor the stb image headers (MIT or Unlicense) in `firmware/esp32/test/third_party/stb/`. Planned dependencies include Lua 5.4 (MIT), ESP-IDF (Apache-2.0), RadioLib (MIT), LVGL (MIT) and Flutter (BSD-3-Clause). Vendored code goes in a `third_party/` folder with its original licence file.

## Map data in a field's image

A field image drawn by the console's *Load the field from a map* (decisions MF-19 to MF-30) is the field's own data, made in the GM's browser and kept on the field controller; it is not part of this repository. It is drawn from OpenStreetMap data (© OpenStreetMap contributors, ODbL) and, where the GM keeps it as the base, the open orthophoto of the country (or region, or German Land) the field is in (decisions MF-65 to MF-80): in mainland Portugal the DGT's (Ortofotomapas © DGT, CC BY 4.0), in Spain IGN España's PNOA (CC BY 4.0, credited with IGN's own formula for a derived work, "Obra derivada de PNOA CC-BY 4.0 scne.es"), in France with Corsica and its overseas departments and collectivities IGN France's orthophotos (Licence Ouverte / Etalab 2.0, "Orthophotos © IGN (Licence Ouverte 2.0)"), in the Netherlands PDOK's aerial photographs (CC BY 4.0, "Luchtfoto © Beeldmateriaal.nl / PDOK (CC BY 4.0)"); in Belgium, Brussels from the NGI-IGN's mosaic (CC BY 4.0, "© NGI-IGN 2023, CC BY 4.0"), Flanders from Digitaal Vlaanderen (Modellicentie Gratis Hergebruik, "Bron: Luchtopnamen Digitaal Vlaanderen") and Wallonia from the SPW (CC BY 4.0, "Source : Service public de Wallonie (SPW) – Orthophotos (CC BY 4.0)"); in Luxembourg the ACT's (CC0, credited anyway: "Orthophoto © ACT Luxembourg (CC0)"); in Switzerland and Liechtenstein swisstopo's SWISSIMAGE (swisstopo's free geodata terms, "© swisstopo"); in eleven German Länder each Land's DOP under its licence and its own credit: Bayern (CC BY 4.0, "Bayerische Vermessungsverwaltung – www.geodaten.bayern.de"), Berlin (dl-de/zero-2-0, "Geoportal Berlin / TrueDOP 2025"), Brandenburg (dl-de/by-2-0, "© GeoBasis-DE/LGB"), Bremen (CC BY 4.0, "© Landesamt GeoInformation Bremen"), Hessen (free of any condition, HVGG § 18, "Geobasisdaten © Hessische Verwaltung für Bodenmanagement und Geoinformation"), Mecklenburg-Vorpommern (CC BY 4.0, "© GeoBasis-DE/M-V <year>"), Nordrhein-Westfalen (dl-de/zero-2-0, "Geobasis NRW"), Rheinland-Pfalz (dl-de/by-2-0, "©GeoBasis-DE / LVermGeoRP (<year>), dl-de/by-2-0, www.lvermgeo.rlp.de"), Saarland (dl-de/by-2-0, "© GeoBasis DE/LVGL-SL 2025"), Sachsen (dl-de/by-2-0, "Quelle: GeoSN") and Thüringen (CC BY 4.0, "© GDI-Th"), the image's credit saying "Daten geändert" where the licence asks changes to be noted; in Poland GUGiK's orthophotomap (free for any use with its source given, "Ortofotomapa: GUGiK (geoportal.gov.pl)"); in Czechia ČÚZK's (CC BY 4.0, "Ortofoto: ČÚZK, <year> (CC BY 4.0)"). Each of these licences allows a commercial field's use, offline, with the attribution, which the image carries in its corner with OpenStreetMap's; the exact wordings are in `controller/console/src/components/ortho-sources.js`. A place the GM searches for by name on that page is found with OpenStreetMap's Nominatim (decisions MF-44 to MF-46): the results are OpenStreetMap data (© OpenStreetMap contributors, ODbL), shown with that attribution and only used to move the map; they are kept in the page's memory while it is open (so the same question is not asked twice) and never saved by the page or sent to the controller. While finding the field, the page's *Ortofoto* layer shows the same orthophotos as map tiles where they cover the map (decisions MF-54, MF-67), with the shown one's credit in the map's corner; the tiles are only viewed, never saved. Where each orthophoto has pictures is each country's (or region's) outline from Natural Earth's admin-0 countries and admin-1 states and provinces (public domain), simplified, in `controller/console/src/components/ortho-coverage.js` (decisions MF-66, MF-73). When OpenStreetMap's main Overpass instance is busy, the same data is fetched from the public instance `overpass.private.coffee` (decision MF-51): it is the same OpenStreetMap data under the same licence (© OpenStreetMap contributors, ODbL) and the same attribution. No imagery is used outside those countries and regions (decisions MF-72, MF-80). The browser tests use made-up fixtures, not OpenStreetMap, Nominatim or any orthophoto's data. No map library is vendored: the console's map viewer is the project's own code.

## Community game modes

Game modes shared through the registry may use any licence from an approved list, shown on each package. Built-in modes in `modes/` are GPL-3.0-or-later.

The approved licences are `GPL-3.0-or-later`, `LGPL-3.0-or-later`, `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause` and `CC0-1.0` (ADR-P5-5); adding one needs an RFC. The registry repository's own data (its index, keys and signatures) is `CC0-1.0`, so anyone may mirror it ([docs/community/registry.md](docs/community/registry.md), decision P5G-9). The registry's template in `registry/template/` and the sample mode in `registry/examples/` are part of this repository.

## The name

Forks are welcome, but please give yours a different name so players can tell it apart from the original Atalaia project.

## Legal review

These licence choices and the app-store permission are pending a legal review before the first public release. Nothing in this repository is legal advice.
