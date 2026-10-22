/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's screen texts (box_text.h). Portuguese is European Portuguese,
 * inclusive (players are "equipas", the game master the "organização"), with
 * what players say on the field. The OLED's texts (TXO_*) fit its 16
 * characters; test_box_text.c checks every entry.
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

box_lang_t box_lang_from_code(const char *code)
{
    if (code != NULL && code[0] == 'p' && code[1] == 't' && (code[2] == '\0' || code[2] == '-')) {
        return BOX_LANG_PT;
    }
    return BOX_LANG_EN;
}

const char *box_lang_code(box_lang_t lang)
{
    return lang == BOX_LANG_PT ? "pt" : "en";
}

static const char *const texts[TX_COUNT][BOX_LANG_COUNT] = {
    [TX_READY_UP] = {"READY", "PRONTA"},
    [TX_HOLD_TO_ARM] = {"Hold to arm", "Mantém premido para armar"},
    [TX_WAITING] = {"Waiting", "À espera"},
    [TX_BOMB_NOT_ARMED] = {"The bomb is not armed", "A bomba não está armada"},
    [TX_ARMED_UP] = {"ARMED", "ARMADA"},
    [TX_UNTIL_DETONATION] = {"until detonation", "até à explosão"},
    [TX_ARMED_BY] = {"Armed by %s", "Armada por %s"},
    [TX_TEAM_WINS] = {"%s team wins", "Vence a equipa %s"},
    [TX_DEFUSED_UP] = {"DEFUSED", "DESARMADA"},
    [TX_EXPLODED_UP] = {"EXPLODED", "EXPLODIU"},
    [TX_GAME_OVER_UP] = {"GAME OVER", "FIM DO JOGO"},
    [TX_SCORES_FINAL] = {"Scores are final", "Pontuações finais"},
    [TX_ZONE_HELD_BY] = {"The zone was held by", "A zona ficou com"},
    [TX_NO_TEAM_HELD] = {"No team held the zone", "Nenhuma equipa ficou com a zona"},
    [TX_PAUSED_UP] = {"PAUSED", "EM PAUSA"},
    [TX_WAIT_GM] = {"Wait for the game master", "Aguarda a organização"},
    [TX_ZONE_UP] = {"ZONE", "ZONA"},
    [TX_NEUTRAL_UP] = {"NEUTRAL", "LIVRE"},
    /* "Mantém premido para capturar" does not fit the screen's width: two lines. */
    [TX_HOLD_TO_CAPTURE] = {"Hold to capture", "Mantém premido"},
    [TX_HOLD_FOR_S] = {"Hold your button for %ld s", "%ld s para capturar a zona"},
    [TX_TO_CAPTURE] = {"", "para capturar a zona"},
    [TX_NOBODY_HOLDS] = {"Nobody holds this zone", "Nenhuma equipa tem esta zona"},
    [TX_ZONE_HELD_UP] = {"ZONE HELD", "ZONA OCUPADA"},
    [TX_HOLD_TO_TAKE_OVER] = {"Hold your button to take it over",
                              "Mantém o botão premido para a tomar"},
    [TX_HELD_SINCE] = {"held since %s", "desde %s"},
    [TX_WAITING_UP] = {"WAITING", "À ESPERA"},
    [TX_GAME_N] = {"Game %u", "Jogo %u"},
    [TX_NOT_STARTED] = {"The game hasn't started", "O jogo ainda não começou"},
    [TX_INVITED_AS] = {"Invited: %s", "Convidada: %s"},
    [TX_JOINED_AS] = {"Joined: %s", "Entrou: %s"},
    [TX_GAME_ON_UP] = {"GAME ON", "JOGO EM CURSO"},
    [TX_NEXT_GAME] = {"Next game", "Próximo jogo"},
    [TX_KEY_FOR_PICKER] = {"Any key: choose a game here", "Uma tecla: escolher jogo aqui"},
    [TX_ROW_GAME] = {"Game", "Jogo"},
    [TX_ROW_CODE] = {"Code", "Código"},
    [TX_ROW_ID] = {"Id", "Id"},
    [TX_ROW_PAIRING] = {"Pairing", "Emparelhar"},
    [TX_ROW_FIELD] = {"Field", "Campo"},
    [TX_ROW_KEY] = {"Key", "Chave"},
    [TX_ROW_TIMER] = {"Timer", "Tempo"},
    [TX_ROW_BATTERY] = {"Battery", "Bateria"},
    [TX_ROW_FIRMWARE] = {"Firmware", "Firmware"},
    [TX_STATUS_UP] = {"STATUS", "ESTADO"},
    [TX_GAME_MASTER_UP] = {"GAME MASTER", "ORGANIZAÇÃO"},
    [TX_ENTER_ADMIN_PIN] = {"Enter the admin PIN", "Marca o PIN de administração"},
    [TX_WRONG_PIN_AGAIN] = {"Wrong PIN, try again", "PIN errado, tenta outra vez"},
    [TX_KEYS_ENTER_DELETE] = {"#  enter        *  delete", "#  confirmar        *  apagar"},
    [TX_CODE_UP] = {"CODE", "CÓDIGO"},
    [TX_CHOOSE_GAME_UP] = {"CHOOSE A GAME", "ESCOLHE UM JOGO"},
    [TX_NO_GAMES] = {"No games stored", "Nenhum jogo guardado"},
    [TX_KEYS_CHOOSE] = {"1-9  choose      #  next      *  back",
                        "1-9  escolher      #  seguinte      *  voltar"},
    [TX_KEYS_CHOOSE_PAGES] = {"1-9  choose    0  more    #  next    *  back",
                              "1-9  escolher   0  mais   #  seguinte   *  voltar"},
    [TX_GAME_TIMER_UP] = {"GAME TIMER", "DURAÇÃO DO JOGO"},
    [TX_KEYS_TIMER] = {"2  +5 min     8  -5 min     #  next     *  back",
                       "2  +5 min    8  -5 min    #  seguinte    *  voltar"},
    [TX_THEN_GAME_ENDS] = {"then the game ends", "e o jogo acaba"},
    [TX_GM_ENDS_IT] = {"the game master ends it", "a organização termina-o"},
    [TX_START_GAME_UP] = {"START THE GAME?", "COMEÇAR O JOGO?"},
    [TX_GAME] = {"Game", "Jogo"},
    [TX_TIMER_IS] = {"Timer: %s", "Duração: %s"},
    [TX_KEYS_START] = {"#  start      *  back", "#  começar      *  voltar"},
    [TX_FIRST_SETUP_UP] = {"FIRST-TIME SETUP", "PRIMEIRA CONFIGURAÇÃO"},
    [TX_JOIN_WIFI] = {"Join the Wi-Fi network", "Liga-te à rede Wi-Fi"},
    [TX_THEN_OPEN] = {"then open 192.168.4.1", "e abre 192.168.4.1"},
    [TX_PHONES_OPEN] = {"Phones usually open it by themselves",
                        "Os telemóveis costumam abri-la sozinhos"},
    [TX_NO_LIMIT] = {"No limit", "Sem limite"},
    [TX_ADOPTED] = {"Adopted", "Adotada"},
    [TX_ALREADY_ADOPTED] = {"Already adopted", "Já adotada"},
    [TX_WRONG_PIN] = {"Wrong PIN", "PIN errado"},
    [TX_ADOPTION_LOCKED] = {"Adoption locked", "Adoção bloqueada"},
    [TX_GAME_JOINED] = {"Game joined", "Em jogo"},
    [TX_NOT_ADOPTED] = {"Not adopted", "Não adotada"},
    [TX_BAD_FIELD_CARD] = {"Bad field card", "Cartão de campo inválido"},
    [TX_NOT_STORED] = {"Not stored", "Não guardado"},
    [TX_ADMIN_PIN_NEEDED] = {"Admin PIN needed", "Falta o PIN"},
    [TX_ADOPTION] = {"Adoption", "Adoção"},
    [TX_PIN_TO_CHANGE_FIELD] = {"PIN to change field", "PIN para mudar de campo"},
    [TX_FIELD_NONE] = {"none", "nenhum"},
    [TX_PAIR_THIS_BOX] = {"Pair this box", "Emparelhar caixa"},
    [TX_PAIR_LOCKED] = {"Pair locked", "Bloqueada"},
    [TX_RESTART_THE_BOX] = {"restart the box", "reinicia a caixa"},
    [TX_PAIR_PAUSED] = {"Pair paused", "Em pausa"},
    [TX_FOR_ONE_MINUTE] = {"for 1 minute", "durante 1 minuto"},
    [TX_TRY_AGAIN] = {"Try again", "Tenta outra vez"},
    [TX_UPDATING] = {"Updating", "A atualizar"},
    [TX_RESTARTING] = {"Restarting", "A reiniciar"},
    [TX_UPDATE_FAILED] = {"Update failed", "Falhou a atualização"},
    [TX_UPDATE_REFUSED] = {"Update refused", "Atualização recusada"},
    [TX_PIN_LOCKED] = {"PIN locked", "PIN bloqueado"},
    [TX_TRY_IN_MIN] = {"Try again in %lu min", "Tenta daqui a %lu min"},
    [TX_NO_ADMIN_PIN] = {"No admin PIN set", "Sem PIN de administração"},
    [TX_SET_ADMIN_PIN] = {"USB console: @admin-pin", "Consola USB: @admin-pin"},
    [TXO_ADMIN_PIN] = {"ADMIN PIN", "PIN ADMIN"},
    [TXO_WRONG_PIN] = {"Wrong PIN", "PIN errado"},
    [TXO_ENTER_DELETE] = {"# enter  * delete", "# ok  * apagar"},
    [TXO_GAMES] = {"GAMES", "JOGOS"},
    [TXO_NO_GAMES] = {"No games", "Sem jogos"},
    [TXO_PICK_PAGES] = {"1-9  0 more  # ok", "1-9  0 mais  # ok"},
    [TXO_PICK] = {"1-9 pick  # ok", "1-9 escolhe # ok"},
    [TXO_GAME_TIME] = {"GAME TIME", "DURAÇÃO"},
    [TXO_TIMER_KEYS] = {"2 +5  8 -5  # ok", "2 +5  8 -5  # ok"},
    [TXO_START_Q] = {"START?", "COMEÇAR?"},
    [TXO_START_BACK] = {"# start  * back", "# sim  * voltar"},
    [TXO_CONSOLE_ADOPT] = {"console: Adopt", "consola: Adotar"},
    [TXO_WIFI_SETUP] = {"WI-FI SETUP", "CONFIGURAR WI-FI"},
    [TXO_OPEN_PORTAL] = {"open 192.168.4.1", "abre 192.168.4.1"},
    [TXO_ARMING] = {"ARMING", "A ARMAR"},
    [TXO_HOLD_TO_ARM] = {"Hold %s to arm", "%s: premir"},
    [TXO_WAIT_GM] = {"Wait for the GM", "Aguarda a org."},
    [TXO_DEFUSE] = {"DEFUSE", "DESARMAR"},
    [TXO_KEY_PICKER] = {"key: game picker", "tecla: jogos"},
    [TXO_NOT_STARTED] = {"not started yet", "não começou"},
    [TXO_HOLD_TO_CAPTURE] = {"Hold to capture", "Premir: capturar"},
    [TXO_PIN_LOCKED] = {"LOCKED", "BLOQUEADO"},
    [TXO_AGAIN_IN_MIN] = {"again in %lu min", "daqui a %lu min"},
    [TXO_NO_PIN] = {"NO PIN", "SEM PIN"},
    [TXO_SET_PIN] = {"@admin-pin", "@admin-pin"},
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
