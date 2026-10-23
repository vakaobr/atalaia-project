/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's screen texts (box_text.h). Portuguese is European Portuguese,
 * inclusive (players are "equipas", the game master the "organização"), with
 * what players say on the field. German (decision P5H-4) addresses players
 * with "du", calls the game master "die Orga" and keeps the loanwords German
 * players use; it was drafted by an AI model and waits for a native-speaking
 * player's review (docs/translations/status.yaml). Traditional Chinese as
 * written in Taiwan (zh-tw, decision P5K-2), drafted the same way and waiting
 * for the same review, uses the words of Taiwan's airsoft players (據點,
 * 啟動/拆除, 主辦, 綁定) and full-width punctuation; its letters are in the
 * fonts because tools/gen_box_fonts.py takes them from this table (P5K-3).
 * The OLED's texts (TXO_*) fit its 16 columns, a Han letter taking two;
 * test_box_text.c checks every entry, and the "_pt", "_de" and "_zh-tw"
 * reference images of test_screens.c and test_oled_screens.c that each
 * screen holds its texts and draws every letter from its own font.
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

/* Traditional Chinese: "zh-tw" or "zh-hant", or either with more subtags ("zh-hant-tw"). Plain
 * "zh", "zh-cn" and "zh-hans" are Simplified Chinese, which the box does not have: English. */
static bool is_zh_tw(const char *code)
{
    if (!is_lang(code, 'z', 'h') || code[2] != '-') return false;
    const char *sub = code + 3;
    size_t n = strcspn(sub, "-");
    return (n == 2 && strncmp(sub, "tw", 2) == 0) || (n == 4 && strncmp(sub, "hant", 4) == 0);
}

box_lang_t box_lang_from_code(const char *code)
{
    if (is_lang(code, 'p', 't')) return BOX_LANG_PT;
    if (is_lang(code, 'd', 'e')) return BOX_LANG_DE;
    if (is_zh_tw(code)) return BOX_LANG_ZH_TW;
    return BOX_LANG_EN;
}

const char *box_lang_code(box_lang_t lang)
{
    switch (lang) {
    case BOX_LANG_PT: return "pt";
    case BOX_LANG_DE: return "de";
    case BOX_LANG_ZH_TW: return "zh-tw";
    default: return "en";
    }
}

static const char *const texts[TX_COUNT][BOX_LANG_COUNT] = {
    [TX_READY_UP] = {"READY", "PRONTA", "BEREIT", "就緒"},
    [TX_HOLD_TO_ARM] = {"Hold to arm", "Mantém premido para armar", "Halten zum Schärfen",
                        "按住以啟動"},
    [TX_WAITING] = {"Waiting", "À espera", "Wartet", "等待中"},
    [TX_BOMB_NOT_ARMED] = {"The bomb is not armed", "A bomba não está armada",
                           "Die Bombe ist nicht scharf", "炸彈尚未啟動"},
    [TX_ARMED_UP] = {"ARMED", "ARMADA", "SCHARF", "已啟動"},
    [TX_UNTIL_DETONATION] = {"until detonation", "até à explosão", "bis zur Explosion", "後引爆"},
    [TX_ARMED_BY] = {"Armed by %s", "Armada por %s", "Scharf gemacht: %s", "由 %s 隊啟動"},
    [TX_TEAM_WINS] = {"%s team wins", "Vence a equipa %s", "Team %s gewinnt", "%s 隊獲勝"},
    [TX_DEFUSED_UP] = {"DEFUSED", "DESARMADA", "ENTSCHÄRFT", "已拆除"},
    [TX_EXPLODED_UP] = {"EXPLODED", "EXPLODIU", "EXPLODIERT", "已爆炸"},
    [TX_GAME_OVER_UP] = {"GAME OVER", "FIM DO JOGO", "SPIEL VORBEI", "遊戲結束"},
    [TX_SCORES_FINAL] = {"Scores are final", "Pontuações finais", "Endstand", "最終分數"},
    [TX_ZONE_HELD_BY] = {"The zone was held by", "A zona ficou com", "Zone gehalten von",
                         "據點最後由此隊佔領"},
    [TX_NO_TEAM_HELD] = {"No team held the zone", "Nenhuma equipa ficou com a zona",
                         "Kein Team hielt die Zone", "沒有隊伍佔領據點"},
    [TX_PAUSED_UP] = {"PAUSED", "EM PAUSA", "PAUSIERT", "已暫停"},
    [TX_WAIT_GM] = {"Wait for the game master", "Aguarda a organização", "Warte auf die Orga",
                    "請等待主辦"},
    [TX_ZONE_UP] = {"ZONE", "ZONA", "ZONE", "據點"},
    [TX_NEUTRAL_UP] = {"NEUTRAL", "LIVRE", "FREI", "中立"},
    /* "Mantém premido para capturar" does not fit the screen's width: two lines. */
    [TX_HOLD_TO_CAPTURE] = {"Hold to capture", "Mantém premido", "Gedrückt halten", "按住按鈕"},
    [TX_HOLD_FOR_S] = {"Hold your button for %ld s", "%ld s para capturar a zona",
                       "%ld s zum Einnehmen", "%ld 秒即可佔領據點"},
    [TX_TO_CAPTURE] = {"", "para capturar a zona", "zum Einnehmen der Zone", "即可佔領據點"},
    [TX_NOBODY_HOLDS] = {"Nobody holds this zone", "Nenhuma equipa tem esta zona",
                         "Kein Team hält diese Zone", "目前沒有隊伍佔領此據點"},
    [TX_ZONE_HELD_UP] = {"ZONE HELD", "ZONA OCUPADA", "ZONE BESETZT", "據點已佔領"},
    [TX_HOLD_TO_TAKE_OVER] = {"Hold your button to take it over",
                              "Mantém o botão premido para a tomar",
                              "Halte den Knopf zum Übernehmen", "按住你的按鈕即可奪取"},
    [TX_HELD_SINCE] = {"held since %s", "desde %s", "seit %s", "自 %s 起佔領"},
    [TX_WAITING_UP] = {"WAITING", "À ESPERA", "WARTEN", "等待中"},
    [TX_GAME_N] = {"Game %u", "Jogo %u", "Spiel %u", "遊戲 %u"},
    [TX_NOT_STARTED] = {"The game hasn't started", "O jogo ainda não começou",
                        "Noch nicht gestartet", "遊戲尚未開始"},
    [TX_INVITED_AS] = {"Invited: %s", "Convidada: %s", "Eingeladen: %s", "已受邀：%s"},
    [TX_JOINED_AS] = {"Joined: %s", "Entrou: %s", "Beigetreten: %s", "已加入：%s"},
    [TX_GAME_ON_UP] = {"GAME ON", "JOGO EM CURSO", "SPIEL LÄUFT", "遊戲進行中"},
    [TX_NEXT_GAME] = {"Next game", "Próximo jogo", "Nächstes Spiel", "下一場"},
    [TX_KEY_FOR_PICKER] = {"Any key: choose a game here", "Uma tecla: escolher jogo aqui",
                           "Taste: hier Spiel wählen", "按任一鍵：在此選擇遊戲"},
    [TX_ROW_GAME] = {"Game", "Jogo", "Spiel", "遊戲"},
    [TX_ROW_CODE] = {"Code", "Código", "Code", "代碼"},
    [TX_ROW_ID] = {"Id", "Id", "ID", "ID"},
    [TX_ROW_PAIRING] = {"Pairing", "Emparelhar", "Koppeln", "配對"},
    [TX_ROW_FIELD] = {"Field", "Campo", "Feld", "場地"},
    [TX_ROW_KEY] = {"Key", "Chave", "Schlüssel", "金鑰"},
    [TX_ROW_TIMER] = {"Timer", "Tempo", "Dauer", "時間"},
    [TX_ROW_BATTERY] = {"Battery", "Bateria", "Akku", "電量"},
    [TX_ROW_FIRMWARE] = {"Firmware", "Firmware", "Firmware", "韌體"},
    [TX_STATUS_UP] = {"STATUS", "ESTADO", "STATUS", "狀態"},
    [TX_GAME_MASTER_UP] = {"GAME MASTER", "ORGANIZAÇÃO", "SPIELLEITUNG", "主辦"},
    [TX_ENTER_ADMIN_PIN] = {"Enter the admin PIN", "Marca o PIN de administração",
                            "Admin-PIN eingeben", "輸入管理 PIN 碼"},
    [TX_WRONG_PIN_AGAIN] = {"Wrong PIN, try again", "PIN errado, tenta outra vez",
                            "Falsche PIN, neuer Versuch", "PIN 碼錯誤，請再試一次"},
    [TX_KEYS_ENTER_DELETE] = {"#  enter        *  delete", "#  confirmar        *  apagar",
                              "#  bestätigen        *  löschen", "#  確認        *  刪除"},
    [TX_CODE_UP] = {"CODE", "CÓDIGO", "CODE", "代碼"},
    [TX_CHOOSE_GAME_UP] = {"CHOOSE A GAME", "ESCOLHE UM JOGO", "SPIEL WÄHLEN", "選擇遊戲"},
    [TX_NO_GAMES] = {"No games stored", "Nenhum jogo guardado", "Keine Spiele gespeichert",
                     "沒有儲存的遊戲"},
    [TX_KEYS_CHOOSE] = {"1-9  choose      #  next      *  back",
                        "1-9  escolher      #  seguinte      *  voltar",
                        "1-9  wählen      #  weiter      *  zurück",
                        "1-9  選擇      #  下一步      *  返回"},
    [TX_KEYS_CHOOSE_PAGES] = {"1-9  choose    0  more    #  next    *  back",
                              "1-9  escolher   0  mais   #  seguinte   *  voltar",
                              "1-9  wählen   0  mehr   #  weiter   *  zurück",
                              "1-9  選擇    0  更多    #  下一步    *  返回"},
    [TX_GAME_TIMER_UP] = {"GAME TIMER", "DURAÇÃO DO JOGO", "SPIELDAUER", "遊戲時間"},
    [TX_KEYS_TIMER] = {"2  +5 min     8  -5 min     #  next     *  back",
                       "2  +5 min    8  -5 min    #  seguinte    *  voltar",
                       "2  +5 min    8  -5 min    #  weiter    *  zurück",
                       "2  +5 分    8  -5 分    #  下一步    *  返回"},
    [TX_THEN_GAME_ENDS] = {"then the game ends", "e o jogo acaba", "dann endet das Spiel",
                           "時間到遊戲就結束"},
    [TX_GM_ENDS_IT] = {"the game master ends it", "a organização termina-o", "die Orga beendet es",
                       "由主辦結束遊戲"},
    [TX_START_GAME_UP] = {"START THE GAME?", "COMEÇAR O JOGO?", "SPIEL STARTEN?", "開始遊戲？"},
    [TX_GAME] = {"Game", "Jogo", "Spiel", "遊戲"},
    [TX_TIMER_IS] = {"Timer: %s", "Duração: %s", "Dauer: %s", "時間：%s"},
    [TX_KEYS_START] = {"#  start      *  back", "#  começar      *  voltar",
                       "#  starten      *  zurück", "#  開始      *  返回"},
    [TX_FIRST_SETUP_UP] = {"FIRST-TIME SETUP", "PRIMEIRA CONFIGURAÇÃO", "ERSTEINRICHTUNG",
                           "首次設定"},
    [TX_JOIN_WIFI] = {"Join the Wi-Fi network", "Liga-te à rede Wi-Fi", "Mit dem WLAN verbinden",
                      "連上這個 Wi-Fi 網路"},
    [TX_THEN_OPEN] = {"then open 192.168.4.1", "e abre 192.168.4.1", "und 192.168.4.1 öffnen",
                      "再開啟 192.168.4.1"},
    [TX_PHONES_OPEN] = {"Phones usually open it by themselves",
                        "Os telemóveis costumam abri-la sozinhos",
                        "Handys öffnen es meist von selbst", "手機通常會自動開啟"},
    [TX_NO_LIMIT] = {"No limit", "Sem limite", "Kein Limit", "不限時"},
    [TX_ADOPTED] = {"Adopted", "Adotada", "Aufgenommen", "已綁定"},
    [TX_ALREADY_ADOPTED] = {"Already adopted", "Já adotada", "Schon aufgenommen", "已經綁定"},
    [TX_WRONG_PIN] = {"Wrong PIN", "PIN errado", "Falsche PIN", "PIN 碼錯誤"},
    [TX_ADOPTION_LOCKED] = {"Adoption locked", "Adoção bloqueada", "Aufnahme gesperrt",
                            "綁定已鎖定"},
    [TX_GAME_JOINED] = {"Game joined", "Em jogo", "Im Spiel", "已加入遊戲"},
    [TX_NOT_ADOPTED] = {"Not adopted", "Não adotada", "Nicht aufgenommen", "尚未綁定"},
    [TX_BAD_FIELD_CARD] = {"Bad field card", "Cartão de campo inválido", "Ungültige Feldkarte",
                           "場地卡無效"},
    [TX_NOT_STORED] = {"Not stored", "Não guardado", "Nicht gespeichert", "未儲存"},
    [TX_ADMIN_PIN_NEEDED] = {"Admin PIN needed", "Falta o PIN", "Admin-PIN fehlt",
                             "需要管理 PIN 碼"},
    [TX_ADOPTION] = {"Adoption", "Adoção", "Aufnahme", "綁定"},
    [TX_PIN_TO_CHANGE_FIELD] = {"PIN to change field", "PIN para mudar de campo",
                                "PIN für Feldwechsel", "換場地要輸入 PIN 碼"},
    [TX_FIELD_NONE] = {"none", "nenhum", "keins", "無"},
    [TX_PAIR_THIS_BOX] = {"Pair this box", "Emparelhar caixa", "Box koppeln", "配對這個盒子"},
    [TX_PAIR_LOCKED] = {"Pair locked", "Bloqueada", "Gesperrt", "配對已鎖定"},
    [TX_RESTART_THE_BOX] = {"restart the box", "reinicia a caixa", "Box neu starten",
                            "請重新啟動盒子"},
    [TX_PAIR_PAUSED] = {"Pair paused", "Em pausa", "Pausiert", "配對已暫停"},
    [TX_FOR_ONE_MINUTE] = {"for 1 minute", "durante 1 minuto", "für 1 Minute", "暫停 1 分鐘"},
    [TX_TRY_AGAIN] = {"Try again", "Tenta outra vez", "Nochmal versuchen", "請再試一次"},
    [TX_UPDATING] = {"Updating", "A atualizar", "Update läuft", "更新中"},
    [TX_RESTARTING] = {"Restarting", "A reiniciar", "Neustart", "重新啟動中"},
    [TX_UPDATE_FAILED] = {"Update failed", "Falhou a atualização", "Update fehlgeschlagen",
                          "更新失敗"},
    [TX_UPDATE_REFUSED] = {"Update refused", "Atualização recusada", "Update abgelehnt",
                           "更新被拒絕"},
    [TX_MODES_FETCHING] = {"Getting modes", "A obter modos", "Lade Modi", "正在取得模式"},
    [TX_MODES_FAILED] = {"Modes refused", "Modos recusados", "Modi abgelehnt", "模式被拒絕"},
    [TX_PIN_LOCKED] = {"PIN locked", "PIN bloqueado", "PIN gesperrt", "PIN 碼已鎖定"},
    [TX_TRY_IN_MIN] = {"Try again in %lu min", "Tente daqui a %lu min", "Erneut in %lu min",
                       "%lu 分鐘後再試"},
    [TX_NO_ADMIN_PIN] = {"No admin PIN set", "Sem PIN de administração", "Keine Admin-PIN",
                         "尚未設定管理 PIN 碼"},
    [TX_SET_ADMIN_PIN] = {"USB console: @admin-pin", "Consola USB: @admin-pin",
                          "USB-Konsole: @admin-pin", "USB 主控台：@admin-pin"},
    [TXO_ADMIN_PIN] = {"ADMIN PIN", "PIN ADMIN", "ADMIN-PIN", "管理 PIN"},
    [TXO_WRONG_PIN] = {"Wrong PIN", "PIN errado", "Falsche PIN", "PIN 碼錯誤"},
    [TXO_ENTER_DELETE] = {"# enter  * delete", "# ok  * apagar", "# ok  * löschen",
                          "# 確認  * 刪除"},
    [TXO_GAMES] = {"GAMES", "JOGOS", "SPIELE", "遊戲"},
    [TXO_NO_GAMES] = {"No games", "Sem jogos", "Keine Spiele", "沒有遊戲"},
    [TXO_PICK_PAGES] = {"1-9  0 more  # ok", "1-9  0 mais  # ok", "1-9  0 mehr  # ok",
                        "1-9 0 更多 # ok"},
    [TXO_PICK] = {"1-9 pick  # ok", "1-9 escolhe # ok", "1-9 wählen # ok", "1-9 選擇 # ok"},
    [TXO_GAME_TIME] = {"GAME TIME", "DURAÇÃO", "SPIELDAUER", "遊戲時間"},
    [TXO_TIMER_KEYS] = {"2 +5  8 -5  # ok", "2 +5  8 -5  # ok", "2 +5  8 -5  # ok",
                        "2 +5  8 -5  # ok"},
    [TXO_START_Q] = {"START?", "COMEÇAR?", "STARTEN?", "開始？"},
    [TXO_START_BACK] = {"# start  * back", "# sim  * voltar", "# ja  * zurück", "# 開始  * 返回"},
    [TXO_CONSOLE_ADOPT] = {"console: Adopt", "consola: Adotar", "GM: Aufnehmen", "控制台：綁定"},
    [TXO_WIFI_SETUP] = {"WI-FI SETUP", "CONFIGURAR WI-FI", "WLAN EINRICHTEN", "Wi-Fi 設定"},
    [TXO_OPEN_PORTAL] = {"open 192.168.4.1", "abre 192.168.4.1", "auf 192.168.4.1",
                         "開 192.168.4.1"},
    [TXO_ARMING] = {"ARMING", "A ARMAR", "SCHARF", "啟動中"},
    [TXO_HOLD_TO_ARM] = {"Hold %s to arm", "%s: premir", "%s: halten", "按住 %s 啟動"},
    [TXO_WAIT_GM] = {"Wait for the GM", "Aguarda a org.", "Warte auf Orga", "等待主辦"},
    [TXO_DEFUSE] = {"DEFUSE", "DESARMAR", "DEFUSE", "拆除"},
    [TXO_KEY_PICKER] = {"key: game picker", "tecla: jogos", "Taste: Spiele", "按鍵：選遊戲"},
    [TXO_NOT_STARTED] = {"not started yet", "não começou", "nicht gestartet", "尚未開始"},
    [TXO_HOLD_TO_CAPTURE] = {"Hold to capture", "Premir: capturar", "Gedrückt halten",
                             "按住以佔領"},
    [TXO_PIN_LOCKED] = {"LOCKED", "BLOQUEADO", "GESPERRT", "已鎖定"},
    [TXO_AGAIN_IN_MIN] = {"again in %lu min", "daqui a %lu min", "Warte %lu min", "%lu 分鐘後再試"},
    [TXO_NO_PIN] = {"NO PIN", "SEM PIN", "KEINE PIN", "無 PIN 碼"},
    [TXO_SET_PIN] = {"@admin-pin", "@admin-pin", "@admin-pin", "@admin-pin"},
    [TXO_POINTS] = {"%ld pts", "%ld pts", "%ld Pkt.", "%ld 分"},
    /* A duration, not the game time of the capture (the TFT's TX_HELD_SINCE). */
    [TXO_HELD_FOR] = {"held for %s", "ocupada %s", "gehalten %s", "已佔領 %s"},
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
