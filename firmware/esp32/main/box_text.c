/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's screen texts (box_text.h). Portuguese is European Portuguese,
 * inclusive (players are "equipas", the game master the "organização"), with
 * what players say on the field. German (decision P5H-4) addresses players
 * with "du", calls the game master "die Orga" and keeps the loanwords German
 * players use; it was drafted by an AI model and waits for a native-speaking
 * player's review (docs/translations/status.yaml). The OLED's texts (TXO_*)
 * fit its 16 characters; test_box_text.c checks every entry, and the
 * "_pt" and "_de" reference images of test_screens.c and
 * test_oled_screens.c that each screen holds its texts.
 */
#include "box_text.h"

#include <stddef.h>
#include <string.h>

static volatile int current = BOX_LANG_EN;
static volatile bool given;

void box_lang_set(box_lang_t lang)
{
    current = lang < BOX_LANG_COUNT ? (int)lang : BOX_LANG_EN;
    given = true;
}

void box_lang_set_code(const char *code)
{
    current = box_lang_from_code(code);
    given = code != NULL && code[0] != 0;
}

bool box_lang_given(void)
{
    return given;
}

box_lang_t box_lang(void)
{
    return (box_lang_t)current;
}

/* "xy" or "xy-..." */
static bool is_lang(const char *code, char a, char b)
{
    return code != NULL && code[0] == a && code[1] == b && (code[2] == '\0' || code[2] == '-');
}

box_lang_t box_lang_from_code(const char *code)
{
    if (is_lang(code, 'p', 't')) return BOX_LANG_PT;
    if (is_lang(code, 'd', 'e')) return BOX_LANG_DE;
    return BOX_LANG_EN;
}

const char *box_lang_code(box_lang_t lang)
{
    switch (lang) {
    case BOX_LANG_PT: return "pt";
    case BOX_LANG_DE: return "de";
    default: return "en";
    }
}

static const char *const texts[TX_COUNT][BOX_LANG_COUNT] = {
    [TX_READY_UP] = {"READY", "PRONTA", "BEREIT"},
    [TX_HOLD_TO_ARM] = {"Hold to arm", "Mantém premido para armar", "Halten zum Schärfen"},
    [TX_WAITING] = {"Waiting", "À espera", "Wartet"},
    [TX_BOMB_NOT_ARMED] = {"The bomb is not armed", "A bomba não está armada",
                           "Die Bombe ist nicht scharf"},
    [TX_ARMED_UP] = {"ARMED", "ARMADA", "SCHARF"},
    [TX_UNTIL_DETONATION] = {"until detonation", "até à explosão", "bis zur Explosion"},
    [TX_ARMED_BY] = {"Armed by %s", "Armada por %s", "Scharf gemacht: %s"},
    [TX_TEAM_WINS] = {"%s team wins", "Vence a equipa %s", "Team %s gewinnt"},
    [TX_DEFUSED_UP] = {"DEFUSED", "DESARMADA", "ENTSCHÄRFT"},
    [TX_EXPLODED_UP] = {"EXPLODED", "EXPLODIU", "EXPLODIERT"},
    [TX_GAME_OVER_UP] = {"GAME OVER", "FIM DO JOGO", "SPIEL VORBEI"},
    [TX_SCORES_FINAL] = {"Scores are final", "Pontuações finais", "Endstand"},
    [TX_ZONE_HELD_BY] = {"The zone was held by", "A zona ficou com", "Zone gehalten von"},
    [TX_NO_TEAM_HELD] = {"No team held the zone", "Nenhuma equipa ficou com a zona",
                         "Kein Team hielt die Zone"},
    [TX_PAUSED_UP] = {"PAUSED", "EM PAUSA", "PAUSIERT"},
    [TX_WAIT_GM] = {"Wait for the game master", "Aguarda a organização", "Warte auf die Orga"},
    [TX_ZONE_UP] = {"ZONE", "ZONA", "ZONE"},
    [TX_NEUTRAL_UP] = {"NEUTRAL", "LIVRE", "FREI"},
    /* "Mantém premido para capturar" does not fit the screen's width: two lines. */
    [TX_HOLD_TO_CAPTURE] = {"Hold to capture", "Mantém premido", "Gedrückt halten"},
    [TX_HOLD_FOR_S] = {"Hold your button for %ld s", "%ld s para capturar a zona",
                       "%ld s zum Einnehmen"},
    [TX_TO_CAPTURE] = {"", "para capturar a zona", "zum Einnehmen der Zone"},
    [TX_NOBODY_HOLDS] = {"Nobody holds this zone", "Nenhuma equipa tem esta zona",
                         "Kein Team hält diese Zone"},
    [TX_ZONE_HELD_UP] = {"ZONE HELD", "ZONA OCUPADA", "ZONE BESETZT"},
    [TX_HOLD_TO_TAKE_OVER] = {"Hold your button to take it over",
                              "Mantém o botão premido para a tomar",
                              "Halte den Knopf zum Übernehmen"},
    [TX_HELD_SINCE] = {"held since %s", "desde %s", "seit %s"},
    [TX_WAITING_UP] = {"WAITING", "À ESPERA", "WARTEN"},
    [TX_GAME_N] = {"Game %u", "Jogo %u", "Spiel %u"},
    [TX_NOT_STARTED] = {"The game hasn't started", "O jogo ainda não começou",
                        "Noch nicht gestartet"},
    [TX_INVITED_AS] = {"Invited: %s", "Convidada: %s", "Eingeladen: %s"},
    [TX_JOINED_AS] = {"Joined: %s", "Entrou: %s", "Beigetreten: %s"},
    [TX_GAME_ON_UP] = {"GAME ON", "JOGO EM CURSO", "SPIEL LÄUFT"},
    [TX_NEXT_GAME] = {"Next game", "Próximo jogo", "Nächstes Spiel"},
    [TX_KEY_FOR_PICKER] = {"Any key: choose a game here", "Uma tecla: escolher jogo aqui",
                           "Taste: hier Spiel wählen"},
    [TX_ROW_GAME] = {"Game", "Jogo", "Spiel"},
    [TX_ROW_CODE] = {"Code", "Código", "Code"},
    [TX_ROW_ID] = {"Id", "Id", "ID"},
    [TX_ROW_PAIRING] = {"Pairing", "Emparelhar", "Koppeln"},
    [TX_ROW_FIELD] = {"Field", "Campo", "Feld"},
    [TX_ROW_KEY] = {"Key", "Chave", "Schlüssel"},
    [TX_ROW_TIMER] = {"Timer", "Tempo", "Dauer"},
    [TX_ROW_BATTERY] = {"Battery", "Bateria", "Akku"},
    [TX_ROW_FIRMWARE] = {"Firmware", "Firmware", "Firmware"},
    [TX_STATUS_UP] = {"STATUS", "ESTADO", "STATUS"},
    [TX_GAME_MASTER_UP] = {"GAME MASTER", "ORGANIZAÇÃO", "SPIELLEITUNG"},
    [TX_ENTER_ADMIN_PIN] = {"Enter the admin PIN", "Marca o PIN de administração",
                            "Admin-PIN eingeben"},
    [TX_WRONG_PIN_AGAIN] = {"Wrong PIN, try again", "PIN errado, tenta outra vez",
                            "Falsche PIN, neuer Versuch"},
    [TX_KEYS_ENTER_DELETE] = {"#  enter        *  delete", "#  confirmar        *  apagar",
                              "#  bestätigen        *  löschen"},
    [TX_CODE_UP] = {"CODE", "CÓDIGO", "CODE"},
    [TX_CHOOSE_GAME_UP] = {"CHOOSE A GAME", "ESCOLHE UM JOGO", "SPIEL WÄHLEN"},
    [TX_NO_GAMES] = {"No games stored", "Nenhum jogo guardado", "Keine Spiele gespeichert"},
    [TX_KEYS_CHOOSE] = {"1-9  choose      #  next      *  back",
                        "1-9  escolher      #  seguinte      *  voltar",
                        "1-9  wählen      #  weiter      *  zurück"},
    [TX_KEYS_CHOOSE_PAGES] = {"1-9  choose    0  more    #  next    *  back",
                              "1-9  escolher   0  mais   #  seguinte   *  voltar",
                              "1-9  wählen   0  mehr   #  weiter   *  zurück"},
    [TX_GAME_TIMER_UP] = {"GAME TIMER", "DURAÇÃO DO JOGO", "SPIELDAUER"},
    [TX_KEYS_TIMER] = {"2  +5 min     8  -5 min     #  next     *  back",
                       "2  +5 min    8  -5 min    #  seguinte    *  voltar",
                       "2  +5 min    8  -5 min    #  weiter    *  zurück"},
    [TX_THEN_GAME_ENDS] = {"then the game ends", "e o jogo acaba", "dann endet das Spiel"},
    [TX_GM_ENDS_IT] = {"the game master ends it", "a organização termina-o", "die Orga beendet es"},
    [TX_START_GAME_UP] = {"START THE GAME?", "COMEÇAR O JOGO?", "SPIEL STARTEN?"},
    [TX_GAME] = {"Game", "Jogo", "Spiel"},
    [TX_TIMER_IS] = {"Timer: %s", "Duração: %s", "Dauer: %s"},
    [TX_KEYS_START] = {"#  start      *  back", "#  começar      *  voltar",
                       "#  starten      *  zurück"},
    [TX_FIRST_SETUP_UP] = {"FIRST-TIME SETUP", "PRIMEIRA CONFIGURAÇÃO", "ERSTEINRICHTUNG"},
    [TX_JOIN_WIFI] = {"Join the Wi-Fi network", "Liga-te à rede Wi-Fi", "Mit dem WLAN verbinden"},
    [TX_THEN_OPEN] = {"then open 192.168.4.1", "e abre 192.168.4.1", "und 192.168.4.1 öffnen"},
    [TX_PHONES_OPEN] = {"Phones usually open it by themselves",
                        "Os telemóveis costumam abri-la sozinhos",
                        "Handys öffnen es meist von selbst"},
    [TX_NO_LIMIT] = {"No limit", "Sem limite", "Kein Limit"},
    [TX_ADOPTED] = {"Adopted", "Adotada", "Aufgenommen"},
    [TX_ALREADY_ADOPTED] = {"Already adopted", "Já adotada", "Schon aufgenommen"},
    [TX_WRONG_PIN] = {"Wrong PIN", "PIN errado", "Falsche PIN"},
    [TX_ADOPTION_LOCKED] = {"Adoption locked", "Adoção bloqueada", "Aufnahme gesperrt"},
    [TX_GAME_JOINED] = {"Game joined", "Em jogo", "Im Spiel"},
    [TX_NOT_ADOPTED] = {"Not adopted", "Não adotada", "Nicht aufgenommen"},
    [TX_BAD_FIELD_CARD] = {"Bad field card", "Cartão de campo inválido", "Ungültige Feldkarte"},
    [TX_NOT_STORED] = {"Not stored", "Não guardado", "Nicht gespeichert"},
    [TX_ADMIN_PIN_NEEDED] = {"Admin PIN needed", "Falta o PIN", "Admin-PIN fehlt"},
    [TX_ADOPTION] = {"Adoption", "Adoção", "Aufnahme"},
    [TX_PIN_TO_CHANGE_FIELD] = {"PIN to change field", "PIN para mudar de campo",
                                "PIN für Feldwechsel"},
    [TX_FIELD_NONE] = {"none", "nenhum", "keins"},
    [TX_PAIR_THIS_BOX] = {"Pair this box", "Emparelhar caixa", "Box koppeln"},
    [TX_PAIR_LOCKED] = {"Pair locked", "Bloqueada", "Gesperrt"},
    [TX_RESTART_THE_BOX] = {"restart the box", "reinicia a caixa", "Box neu starten"},
    [TX_PAIR_PAUSED] = {"Pair paused", "Em pausa", "Pausiert"},
    [TX_FOR_ONE_MINUTE] = {"for 1 minute", "durante 1 minuto", "für 1 Minute"},
    [TX_TRY_AGAIN] = {"Try again", "Tenta outra vez", "Nochmal versuchen"},
    [TX_UPDATING] = {"Updating", "A atualizar", "Update läuft"},
    [TX_RESTARTING] = {"Restarting", "A reiniciar", "Neustart"},
    [TX_UPDATE_FAILED] = {"Update failed", "Falhou a atualização", "Update fehlgeschlagen"},
    [TX_UPDATE_REFUSED] = {"Update refused", "Atualização recusada", "Update abgelehnt"},
    [TX_MODES_FETCHING] = {"Getting modes", "A obter modos", "Lade Modi"},
    [TX_MODES_FAILED] = {"Modes refused", "Modos recusados", "Modi abgelehnt"},
    [TX_PIN_LOCKED] = {"PIN locked", "PIN bloqueado", "PIN gesperrt"},
    [TX_TRY_IN_MIN] = {"Try again in %lu min", "Tente daqui a %lu min", "Erneut in %lu min"},
    [TX_NO_ADMIN_PIN] = {"No admin PIN set", "Sem PIN de administração", "Keine Admin-PIN"},
    [TX_SET_ADMIN_PIN] = {"USB console: @admin-pin", "Consola USB: @admin-pin",
                          "USB-Konsole: @admin-pin"},
    [TXO_ADMIN_PIN] = {"ADMIN PIN", "PIN ADMIN", "ADMIN-PIN"},
    [TXO_WRONG_PIN] = {"Wrong PIN", "PIN errado", "Falsche PIN"},
    [TXO_ENTER_DELETE] = {"# enter  * delete", "# ok  * apagar", "# ok  * löschen"},
    [TXO_GAMES] = {"GAMES", "JOGOS", "SPIELE"},
    [TXO_NO_GAMES] = {"No games", "Sem jogos", "Keine Spiele"},
    [TXO_PICK_PAGES] = {"1-9  0 more  # ok", "1-9  0 mais  # ok", "1-9  0 mehr  # ok"},
    [TXO_PICK] = {"1-9 pick  # ok", "1-9 escolhe # ok", "1-9 wählen # ok"},
    [TXO_GAME_TIME] = {"GAME TIME", "DURAÇÃO", "SPIELDAUER"},
    [TXO_TIMER_KEYS] = {"2 +5  8 -5  # ok", "2 +5  8 -5  # ok", "2 +5  8 -5  # ok"},
    [TXO_START_Q] = {"START?", "COMEÇAR?", "STARTEN?"},
    [TXO_START_BACK] = {"# start  * back", "# sim  * voltar", "# ja  * zurück"},
    [TXO_CONSOLE_ADOPT] = {"console: Adopt", "consola: Adotar", "GM: Aufnehmen"},
    [TXO_WIFI_SETUP] = {"WI-FI SETUP", "CONFIGURAR WI-FI", "WLAN EINRICHTEN"},
    [TXO_OPEN_PORTAL] = {"open 192.168.4.1", "abre 192.168.4.1", "auf 192.168.4.1"},
    [TXO_ARMING] = {"ARMING", "A ARMAR", "SCHARF"},
    [TXO_HOLD_TO_ARM] = {"Hold %s to arm", "%s: premir", "%s: halten"},
    [TXO_WAIT_GM] = {"Wait for the GM", "Aguarda a org.", "Warte auf Orga"},
    [TXO_DEFUSE] = {"DEFUSE", "DESARMAR", "DEFUSE"},
    [TXO_KEY_PICKER] = {"key: game picker", "tecla: jogos", "Taste: Spiele"},
    [TXO_NOT_STARTED] = {"not started yet", "não começou", "nicht gestartet"},
    [TXO_HOLD_TO_CAPTURE] = {"Hold to capture", "Premir: capturar", "Gedrückt halten"},
    [TXO_PIN_LOCKED] = {"LOCKED", "BLOQUEADO", "GESPERRT"},
    [TXO_AGAIN_IN_MIN] = {"again in %lu min", "daqui a %lu min", "Warte %lu min"},
    [TXO_NO_PIN] = {"NO PIN", "SEM PIN", "KEINE PIN"},
    [TXO_SET_PIN] = {"@admin-pin", "@admin-pin", "@admin-pin"},
};

const char *box_text_in(box_lang_t lang, box_text_id_t id)
{
    if ((unsigned)id >= (unsigned)TX_COUNT) return "";
    if ((unsigned)lang >= (unsigned)BOX_LANG_COUNT) lang = BOX_LANG_EN;
    const char *s = texts[id][lang];
    if (s == NULL) s = texts[id][BOX_LANG_EN];
    return s != NULL ? s : "";
}

const char *box_text(box_text_id_t id)
{
    return box_text_in(box_lang(), id);
}
