<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Sharing terms: cross-field chronograph sharing (GDPR Article 26)

**Version 2026-10-30.** The version is in `atalaia_server/sharing_terms.py` (`DEFAULT_VERSION`) and is what the
software records when a field accepts these terms. Change the text, change the version: every field is then asked to
accept again, and its sharing is suspended until it does. A Portuguese version is in
[`sharing-terms-pt.md`](sharing-terms-pt.md); both say the same.

> **Template, not legal advice.** The arrangement follows the positions agreed with the project's lawyer (decision
> LEG-40 to LEG-59). A hub operator or a field that adopts it should have its own lawyer check the final wording.
> Text in [BRACKETS] is filled in by whoever publishes the terms.

These terms are the **arrangement between joint controllers** that Article 26 GDPR asks for. They are accepted **in the
software**, by a field's administrator, when the field switches cross-field chrono sharing on (the server's staff
settings page, section "Sharing terms"). The software records which version was accepted, when, and by which account.
Nobody negotiates with another field: every field that shares accepts the same terms.

## 1. Parties

The **fields** that have chrono sharing switched on in the same hub or site server (each a **field**, together the
**fields**). Each field is represented by the legal person that runs it (a club, association or company). The
**hub operator** ([HUB OPERATOR'S LEGAL NAME]) runs the server and is not a party: it is a processor (section 3).

## 2. What these terms cover, and what they do not

Cross-field sharing is one stage of processing: a field **publishes** the signed chronograph readings of a person to
the other fields that share, and those fields' staff **read** them. These terms cover that stage only.

Each field remains **sole controller** of everything before it (the readings it makes, stores and signs at its own
field) and after it (what its own staff decide, record or do with what they read, including any violation or
decision). Those parts are governed by the field's own privacy notice, not by these terms.

## 3. Roles

1. Each field is the **controller** of its own players' data.
2. The **hub operator** is a **processor** for each field under the data processing agreement (`dpa-template.md`,
   Art. 28(3)). For the shared tables it processes **as processor of the fields jointly**, on these terms.
3. For the sharing stage only, the fields are **joint controllers** (Art. 26): they pursue one purpose (the safety of
   replicas across fields) through one system whose means they accept together by switching sharing on.
4. The Atalaia project (the authors of the free software) is **not** a controller or a processor of any field's data.
5. The data is processed only in the hub or site server the fields use, in a data centre inside the EU/EEA as the DPA
   requires. These terms add no transfer outside the EU/EEA.

## 4. Scope of the data

Only the **signed chronograph readings** of people who gave consent for **both** the field that made the reading and
the field that reads it: the signed record exactly as the marshal's phone signed it (with the marshal's public key),
and nothing else. **Not shared:** names, violations, what staff decided, check-in data, registration data, positions,
and any other data of the person. The person's accounts at two fields are linked only by the person, with a one-time
code; nothing is matched by e-mail address or user name.

## 5. Purpose, and what it may not be used for

The purpose is **replica safety**: a field can see that a replica measured over the limit elsewhere before it lets the
replica play.

The shared readings are **never** used for marketing, for scoring or ranking people, or for **refusing entry on the
other field's readings alone**: staff always measure the replica themselves before deciding anything. A field that
uses a shared reading for any other purpose is the sole controller of that use and breaches these terms.

## 6. Lawful basis, and the person's choices

The basis is the **person's consent** (Art. 6(1)(a)), asked **separately for each field**: a person may share with one
field and not with another. The consent screen says which fields share. The person may withdraw consent per field at
any time; withdrawing, unlinking the accounts or erasing the account **removes the published copies at once** in the
software.

## 7. Information to people (Art. 13, 14 and 26(2))

1. Each field informs its own players in its privacy notice, section 2.4, which states the essence of this
   arrangement: that the field shares chrono readings with other fields on the person's separate consent, which data,
   why, and that the person may go to any participating field.
2. The consent screen lists the fields that share.
3. Each field gives these terms (or their essence) to a person who asks.

## 8. Rights of the person

A person may exercise their rights (access, rectification, erasure, restriction, objection, withdrawal of consent)
against **any** participating field, whatever these terms say (Art. 26(3)). The field that receives a request about
shared data **handles it or forwards it to the right field within 7 days** and tells the person. Withdrawal of consent
and erasure of the account work in the software at once. A field answers for the requests it receives.

## 9. Security

Each field keeps its own data secure. The shared data is kept by the hub operator under the DPA's security measures:
each field's data in its own database schema with row-level security; another field's readings reachable only through
one read function that checks that both fields share and that the person consented for both; read-only for the
reading field; audited. A reading carries its signature, so the reading field can check it without trusting the server.

## 10. Personal data breaches

The field that finds a breach involving shared data **tells the other fields and the hub operator within 48 hours**
with what it knows. Each field notifies the supervisory authority (in Portugal, the CNPD) **for the data it is
responsible for** within 72 hours (Art. 33), and the people affected where Article 34 requires. The hub operator tells
the fields of a breach it finds within 48 hours (DPA, section 9).

## 11. Retention

A shared copy lives only while the field has sharing switched on, the person's consent for that field is live and the
accounts are linked, and it follows the original: the daily retention purge makes the published copies say again what
the field's own records say. The copy a reading field keeps on its controller is kept apart, for the roster of the game only, for at most 365 days, and
deleted with the person's erasure.

## 12. Leaving, and changes

1. A field that **switches sharing off** stops reading at once, and the copies it published are deleted.
2. When these terms change, the **version** changes. Every field is asked to accept the new version, and **until it
   does, its sharing is suspended** (it neither publishes nor reads; its switch stays on). The other fields are not
   affected.
3. A field that does not accept the new version stays out of the sharing without any other consequence.

## 13. Liability, law and courts

Towards a person each field is liable as the law provides (Art. 82 GDPR, and the person's rights under Art. 26(3)
are not limited by these terms); between the fields, each answers for the part of the processing it controls
(section 2). Portuguese law; the courts of [CITY].
