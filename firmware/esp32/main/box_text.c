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
#include <stdio.h>
#include <string.h>
#include <strings.h>

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
    [TX_CODE_UP] = {"CODE", "CÓDIGO", "CODE", "密碼"},
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
    [TX_TRY_IN_MIN] = {"Try again in %lu min", "Tenta daqui a %lu min", "Erneut in %lu min",
                       "%lu 分鐘後再試"},
    [TX_NO_ADMIN_PIN] = {"No admin PIN set", "Sem PIN de administração", "Keine Admin-PIN",
                         "尚未設定管理 PIN 碼"},
    [TX_SET_ADMIN_PIN] = {"USB console: @admin-pin", "Consola USB: @admin-pin",
                          "USB-Konsole: @admin-pin", "USB 主控台：@admin-pin"},
    /* The picker's last entry, and its confirmation: the box restarts into its setup portal. */
    [TX_SETUP_ITEM] = {"Wi-Fi setup", "Configurar o Wi-Fi", "WLAN einrichten", "Wi-Fi 設定"},
    [TX_SETUP_AGAIN_UP] = {"SET UP AGAIN?", "CONFIGURAR DE NOVO?", "NEU EINRICHTEN?", "重新設定？"},
    [TX_SETUP_WARNING] = {"The box restarts and opens its Wi-Fi setup",
                          "A caixa reinicia e abre a configuração Wi-Fi",
                          "Die Box startet neu und öffnet die WLAN-Einrichtung",
                          "盒子會重新啟動，開啟設定"},
    [TX_KEYS_SETUP] = {"#  set up      *  back", "#  configurar      *  voltar",
                       "#  einrichten      *  zurück", "#  設定      *  返回"},
    [TX_TITLE_ARM] = {"ARM", "ARMAR", "SCHÄRFEN", "啟動"},
    [TX_TITLE_DEFUSE] = {"DEFUSE", "DESARMAR", "ENTSCHÄRFEN", "拆除"},
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
    [TXO_DEFUSE] = {"DEFUSE", "DESARM.", "ENTSCH.", "拆除"},
    [TXO_KEY_PICKER] = {"key: game picker", "tecla: jogos", "Taste: Spiele", "按鍵：選遊戲"},
    [TXO_NOT_STARTED] = {"not started yet", "não começou", "nicht gestartet", "尚未開始"},
    [TXO_HOLD_TO_CAPTURE] = {"Hold to capture", "Premir: capturar", "Gedrückt halten",
                             "按住以佔領"},
    [TXO_PIN_LOCKED] = {"LOCKED", "BLOQUEADO", "GESPERRT", "已鎖定"},
    [TXO_AGAIN_IN_MIN] = {"again in %lu min", "daqui a %lu min", "Warte %lu min", "%lu 分鐘後再試"},
    [TXO_NO_PIN] = {"NO PIN", "SEM PIN", "KEINE PIN", "無 PIN 碼"},
    [TXO_SET_PIN] = {"@admin-pin", "@admin-pin", "@admin-pin", "@admin-pin"},
    [TXO_SETUP_Q] = {"Set up again?", "Reconfigurar?", "Neu einrichten?", "重新設定？"},
    [TXO_KEYS_SETUP] = {"# ok  * back", "# ok  * voltar", "# ok  * zurück", "# 確認  * 返回"},
    [TXO_POINTS] = {"%ld pts", "%ld pts", "%ld Pkt.", "%ld 分"},
    /* A duration, not the game time of the capture (the TFT's TX_HELD_SINCE). */
    [TXO_HELD_FOR] = {"held for %s", "ocupada %s", "gehalten %s", "已佔領 %s"},
    /* The OLED's header: a built-in mode's name (16 columns, a Han letter two). */
    [TXO_M_BOMB] = {"BOMB", "BOMBA", "BOMBE", "炸彈"},
    [TXO_M_DOMINATION] = {"DOMINATION", "DOMÍNIO", "DOMINATION", "佔點"},
    [TXO_M_HOLDALL] = {"HOLDALL", "DOMÍNIO TOTAL", "HOLD-ALL", "全佔點"},
    [TXO_M_LASTSTAND] = {"LASTSTAND", "ÚLTIMO ELEMENTO", "LAST STAND", "最後一人"},
    [TXO_M_CODES] = {"CODES", "CÓDIGOS", "CODES", "密碼"},
    [TXO_M_KILLCONF] = {"KILL CONFIRMED", "BAIXA CONF.", "KILL CONFIRMED", "擊殺確認"},
    [TXO_M_RESPAWN] = {"RESPAWN", "REENTRADAS", "RESPAWN", "復活"},
    [TXO_M_CHECKIN] = {"PLAYER CHECKIN", "REGISTO", "CHECK-IN", "玩家報到"},
    [TXO_M_MEDIC] = {"MEDIC", "LIGADURAS", "MEDIC-KIT", "醫護包"},
    [TXO_M_MASTERSAT] = {"MASTER SATELLITES", "MESTRE E SATÉL.", "MASTER/SAT.", "主站與衛星"},
    [TXO_M_HACKING] = {"HACKING TERMINAL", "HACKEIA", "HACKING", "駭客終端"},
    [TXO_M_VIP] = {"VIP PAYLOAD", "VIP / CARGA", "VIP / PAYLOAD", "VIP / 護送"},
    [TXO_M_OBJECTIVES] = {"OBJECTIVES", "OBJETIVOS", "ZIELE", "任務目標"},
    [TXO_M_MONEY] = {"MONEY FACTORY", "FÁBRICA", "MONEY FACTORY", "印鈔廠"},
    [TXO_M_TARGETS] = {"TARGET WINDOWS", "JANELAS DE ALVO", "ZIELFENSTER", "標靶時窗"},
    [TXO_M_PROGDOM] = {"PROGRESSIVE DOMINATION", "PROGRESSIVO", "PROGRESSIVE", "漸進佔點"},
    /* The OLED's middle line: a built-in template's name where it has no countdown. */
    [TXO_S_TAGS] = {"TAGS", "ETIQUETAS", "TAGS", "標籤"},
    [TXO_S_RESPAWN] = {"RESPAWN", "REENTRADA", "RESPAWN", "復活"},
    [TXO_S_CHECKIN] = {"CHECK-IN", "PRESENÇA", "CHECK-IN", "報到"},
    [TXO_S_SEQUENCE] = {"SEQUENCE", "SEQUÊNCIA", "FOLGE", "順序"},
    [TXO_S_SOLVED] = {"SOLVED", "RESOLVIDO", "GELÖST", "已破解"},
    [TXO_S_WIRES] = {"WIRES", "FIOS", "DRÄHTE", "電線"},
    [TXO_S_MASTER] = {"MASTER", "MESTRE", "MASTER", "主站"},
    [TXO_S_EMPTY] = {"EMPTY", "VAZIO", "LEER", "已用完"},
    [TXO_S_HEALED] = {"HEALED", "TRATADO", "BEHANDELT", "已治療"},
    [TXO_S_HEALING] = {"HEALING", "A TRATAR", "BEHANDLUNG", "治療中"},
    [TXO_S_REFUSED] = {"REFUSED", "RECUSADO", "ABGELEHNT", "已拒絕"},
    [TXO_S_BANK] = {"BANK", "BANCO", "BANK", "銀行"},
    [TXO_S_FACTORY] = {"FACTORY", "FÁBRICA", "FABRIK", "印鈔廠"},
    [TXO_S_COLLECTED] = {"COLLECTED", "RECOLHIDO", "ABGEHOLT", "已領取"},
    [TXO_S_DEPOSITED] = {"DEPOSITED", "DEPOSITADO", "EINGEZAHLT", "已存入"},
    [TXO_S_CAPTURE] = {"CAPTURE", "CAPTURA", "EINNEHMEN", "佔領"},
    [TXO_S_TARGET] = {"TARGET", "ALVO", "ZIELSCHEIBE", "標靶"},
    [TXO_S_PAYLOAD] = {"PAYLOAD", "CARGA", "PAYLOAD", "護送"},
    [TXO_S_HELD] = {"HELD", "OCUPADO", "BESETZT", "已佔領"},
    [TXO_S_INACTIVE] = {"INACTIVE", "INATIVA", "INAKTIV", "未啟用"},
    [TXO_S_COMPLETED] = {"COMPLETED", "COMPLETA", "FERTIG", "已完成"},
};

typedef struct {
    const char *name; /* the English name */
    box_text_id_t id;
} name_map_t;

static const name_map_t mode_names[] = {
    {"BOMB", TXO_M_BOMB},
    {"DOMINATION", TXO_M_DOMINATION},
    {"HOLDALL", TXO_M_HOLDALL},
    {"LASTSTAND", TXO_M_LASTSTAND},
    {"CODES", TXO_M_CODES},
    {"KILL CONFIRMED", TXO_M_KILLCONF},
    {"RESPAWN", TXO_M_RESPAWN},
    {"PLAYER CHECKIN", TXO_M_CHECKIN},
    {"MEDIC", TXO_M_MEDIC},
    {"MASTER SATELLITES", TXO_M_MASTERSAT},
    {"HACKING TERMINAL", TXO_M_HACKING},
    {"VIP PAYLOAD", TXO_M_VIP},
    {"OBJECTIVES", TXO_M_OBJECTIVES},
    {"MONEY FACTORY", TXO_M_MONEY},
    {"TARGET WINDOWS", TXO_M_TARGETS},
    {"PROGRESSIVE DOMINATION", TXO_M_PROGDOM},
};

/* Every built-in template the OLED's generic line names (final_score, the countdowns and the
 * zone screens have their own lines in oled_view.c). */
static const name_map_t screen_names[] = {
    {"defused", TX_DEFUSED_UP},
    {"exploded", TX_EXPLODED_UP},
    {"tags", TXO_S_TAGS},
    {"respawn", TXO_S_RESPAWN},
    {"checkin", TXO_S_CHECKIN},
    {"hack_code", TX_CODE_UP},
    {"hack_sequence", TXO_S_SEQUENCE},
    {"hack_solved", TXO_S_SOLVED},
    {"hack_wires", TXO_S_WIRES},
    {"master_status", TXO_S_MASTER},
    {"medic_empty", TXO_S_EMPTY},
    {"medic_healed", TXO_S_HEALED},
    {"medic_hold", TXO_S_HEALING},
    {"medic_idle", TX_READY_UP},
    {"medic_refused", TXO_S_REFUSED},
    {"refused", TXO_S_REFUSED},
    {"bank", TXO_S_BANK},
    {"factory", TXO_S_FACTORY},
    {"collected", TXO_S_COLLECTED},
    {"deposited", TXO_S_DEPOSITED},
    {"obj_bomb", TXO_M_BOMB},
    {"obj_capture", TXO_S_CAPTURE},
    {"obj_code", TX_CODE_UP},
    {"obj_status", TX_STATUS_UP},
    {"obj_tags", TXO_S_TAGS},
    {"window", TXO_S_TARGET},
    {"payload", TXO_S_PAYLOAD},
    {"checkpoint_free", TX_NEUTRAL_UP},
    {"checkpoint_held", TXO_S_HELD},
    {"inactive", TXO_S_INACTIVE},
    {"completed", TXO_S_COMPLETED},
};

static const char *lookup(const name_map_t *map, size_t n, const char *name)
{
    if (name == NULL || box_lang() == BOX_LANG_EN) return NULL;
    for (size_t i = 0; i < n; i++) {
        if (strcmp(map[i].name, name) == 0) return box_text(map[i].id);
    }
    return NULL;
}

const char *box_text_mode_name(const char *mode_upper)
{
    return lookup(mode_names, sizeof(mode_names) / sizeof(mode_names[0]), mode_upper);
}

const char *box_text_screen_name(const char *template_name)
{
    return lookup(screen_names, sizeof(screen_names) / sizeof(screen_names[0]), template_name);
}

const char *box_text_title(const char *title)
{
    if (title == NULL) return "";
    if (strcasecmp(title, "ARM") == 0) return box_text(TX_TITLE_ARM);
    if (strcasecmp(title, "DEFUSE") == 0) return box_text(TX_TITLE_DEFUSE);
    if (strcasecmp(title, "CODE") == 0) return box_text(TX_CODE_UP);
    return title;
}

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

const char *box_text_fill_lang(const char *params_json, char *out, size_t cap)
{
    if (params_json == NULL || out == NULL || cap == 0) return params_json;
    /* "lang" : "" with any spaces around the colon; the key may not be the end of a longer one
     * (the quote before it) or inside a string (a quote there is escaped, so a backslash). */
    for (const char *p = strstr(params_json, "\"lang\""); p != NULL;
         p = strstr(p + 1, "\"lang\"")) {
        if (p > params_json && p[-1] == '\\') continue;
        const char *q = p + 6;
        while (*q == ' ') q++;
        if (*q != ':') continue;
        q++;
        while (*q == ' ') q++;
        if (q[0] != '"' || q[1] != '"') return params_json;
        const char *code = box_lang_code(box_lang());
        size_t head = (size_t)(q + 1 - params_json); /* up to and with the opening quote */
        int n = snprintf(out, cap, "%.*s%s%s", (int)head, params_json, code, q + 1);
        return n > 0 && (size_t)n < cap ? out : params_json;
    }
    return params_json;
}
