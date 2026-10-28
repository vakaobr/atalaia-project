// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Português europeu, a língua por omissão da app (strings.dart).
library;

const Map<String, String> ptStrings = {
  // Comum
  'common.cancel': 'Cancelar',
  'common.close': 'Fechar',
  'common.clear': 'Apagar o texto',
  'common.ok': 'OK',
  'common.save': 'Guardar',

  // Início e funções
  'home.choose': 'O que vais fazer neste telemóvel?',
  'home.no_prop':
      'Neste telemóvel não há dispositivo de jogo: só o Android pode ser '
      'um dispositivo de jogo (precisa de modo quiosque, NFC em segundo plano '
      'e USB).',
  'role.prop': 'Dispositivo de jogo',
  'role.prop_hint':
      'Este telemóvel faz de caixa: corre o modo de jogo, com botões das '
      'equipas no ecrã, etiquetas NFC e um módulo de E/S opcional.',
  'role.player': 'Participante',
  'role.player_hint':
      'Segue o jogo em curso: tempo, pontuação, objetivos, vidas e '
      'mensagens da organização.',
  'role.marshal': 'Marshal',
  'role.marshal_hint':
      'Cronografagem à entrada e verificações durante o jogo, registo de '
      'réplicas e etiquetas de quem joga.',
  'role.gm': 'Organização',
  'role.gm_hint':
      'A consola da organização, servida pelo controlador de campo.',
  'role.controller': 'Controlador de campo',
  'role.controller_hint':
      'Este telemóvel corre o jogo sem Raspberry Pi: a consola, o check-in e '
      'as caixas através de um módulo de E/S.',

  // Definições
  'settings.title': 'Definições',
  'settings.language': 'Língua',
  'settings.lang_pt': 'Português',
  'settings.lang_en': 'English',
  'settings.lang_de': 'Deutsch',
  'settings.lang_zh-tw': '中文（台灣）',
  'settings.theme': 'Aspeto',
  'settings.theme_system': 'Do sistema',
  'settings.theme_dark': 'Escuro',
  'settings.theme_light': 'Claro (sol)',
  'settings.field': 'Campo',
  'settings.join_key': 'Chave de entrada do campo',
  'settings.join_key_none': 'Por definir: sem ela não dá para entrar em jogos.',
  'settings.join_key_set': 'Definida (termina em …{end})',
  'settings.join_key_hint':
      'Os 64 algarismos hexadecimais que o controlador de campo mostra com '
      '«python3 -m atalaia_controller join-key». Confirmam que um cartão ou '
      'código QR de entrada é deste campo.',
  'settings.join_key_bad':
      'A chave de entrada tem 64 algarismos hexadecimais (0-9, a-f).',
  'settings.join_key_clear': 'Apagar',
  'settings.pin': 'PIN da organização',
  'settings.pin_none':
      'Sem PIN: qualquer pessoa pode pausar ou terminar um jogo neste '
      'dispositivo.',
  'settings.pin_set': 'Definido: pedido para começar, pausar, terminar e sair.',
  'settings.pin_hint': '4 a 8 algarismos.',
  'settings.pin_remove': 'Tirar o PIN',
  'settings.kiosk': 'Modo quiosque',
  'settings.kiosk_hint':
      'Durante um jogo o telemóvel fica preso à app (fixação de ecrã). Se '
      'alguém sair, a app avisa.',
  'settings.vibrate': 'Vibrar nos eventos do jogo',
  'settings.vibrate_hint':
      'Uma vibração curta para uma mensagem da organização, uma caixa da tua '
      'equipa capturada ou perdida, o início ou o fim do jogo, a caixa '
      'seguinte a ficar ativa na Dominação Progressiva e novas ordens (um '
      'objetivo ou as do teu líder de squad). Sem som. Valem as definições '
      'de silêncio do telemóvel.',
  'settings.about': 'Sobre',
  'settings.version': 'Atalaia {version}',
  'settings.core': 'Núcleo de jogo {version}',
  'settings.no_core': 'Sem núcleo de jogo neste telemóvel.',
  'settings.licence': 'Licença',
  'settings.licence_text':
      'Software livre: GPL-3.0 ou posterior, com a permissão adicional para '
      'lojas de aplicações (APP-STORE-PERMISSION.md).',
  'pin.title': 'PIN da organização',
  'pin.wrong': 'PIN errado.',

  // Bateria
  'battery.title': 'Bateria e segundo plano',
  'battery.intro':
      'Durante um jogo, o Android pode parar apps em segundo plano para '
      'poupar bateria. Para um dispositivo de jogo aguentar horas de jogo, '
      'tira a Atalaia da otimização de bateria.',
  'battery.exempt': 'A Atalaia já está fora da otimização de bateria.',
  'battery.not_exempt':
      'A Atalaia ainda está sujeita à otimização de bateria: o Android pode '
      'pará-la a meio de um jogo.',
  'battery.request': 'Pedir a isenção',
  'battery.open_settings': 'Abrir as definições de bateria',
  'battery.on_samsung_title': 'Samsung',
  'battery.on_samsung':
      'Definições › Bateria › Limites de utilização em segundo plano: tira a '
      'Atalaia das apps em suspensão. Depois, Definições › Apps › Atalaia › '
      'Bateria › Sem restrições.',
  'battery.on_xiaomi_title': 'Xiaomi, Redmi, POCO',
  'battery.on_xiaomi':
      'Definições › Bateria › Poupança de bateria das apps › Atalaia › Sem '
      'restrições. Em Segurança › Arranque automático, liga a Atalaia.',
  'battery.on_huawei_title': 'Huawei, Honor',
  'battery.on_huawei':
      'Definições › Bateria › Arranque de apps › Atalaia: desliga a gestão '
      'automática e deixa ligadas as três opções (arranque automático, '
      'secundário e em segundo plano).',
  'battery.on_oneplus_title': 'OnePlus, OPPO, realme',
  'battery.on_oneplus':
      'Definições › Bateria › Otimização da bateria › Atalaia › Não otimizar. '
      'Em alguns modelos também: Definições › Apps › Atalaia › Utilização da '
      'bateria › Permitir em segundo plano.',
  'battery.on_generic_title': 'Outros telemóveis',
  'battery.on_generic':
      'Definições › Apps › Atalaia › Bateria: escolhe «Sem restrições» ou '
      '«Não otimizar». O nome varia de marca para marca.',

  // Dispositivo de jogo
  'prop.intro':
      'Um jogo novo só neste telemóvel, ou um jogo do controlador de campo '
      '(com o cartão ou o código QR de entrada que a organização gera).',
  'prop.new_game': 'Novo jogo',
  'prop.join': 'Entrar num jogo',
  'prop.capabilities': 'O que este telemóvel tem',
  'prop.start': 'Começar',
  'prop.confirm_start': 'Começar o jogo agora?',
  'prop.pause': 'Pausa',
  'prop.resume': 'Retomar',
  'prop.end': 'Terminar o jogo',
  'prop.confirm_end': 'Terminar o jogo agora?',
  'prop.leave': 'Sair',
  'prop.confirm_leave': 'Sair do jogo?',
  'prop.confirm_leave_body':
      'O jogo ainda está a decorrer: este dispositivo deixa de contar.',
  'prop.log': 'Registo do jogo',
  'prop.admin': 'Organização',
  'prop.loading': 'A carregar o modo…',
  'prop.waiting': 'À espera do início',
  'prop.paused': 'PAUSA',
  'prop.paused_hint': 'Aguarda pela organização.',
  'prop.ended': 'Fim do jogo',
  'prop.script_error': 'O modo parou',
  'prop.tamper':
      'Alguém saiu do modo quiosque durante o jogo. Avisa a organização.',
  'prop.pod_opened':
      'Alguém abriu o módulo de E/S durante o jogo. Avisa a organização.',
  'prop.pod_reconnecting':
      'A ligação ao módulo de E/S perdeu-se. A religar (tentativa {n})…',
  'prop.pod_refused':
      'Respondeu outro módulo, por isso o módulo de E/S deixou de estar ligado. Liga um módulo outra vez.',
  'prop.pod_unlink': 'Desligar o módulo de E/S',
  'prop.hold': 'Manter premido\n{team}',
  'prop.nfc_hint': 'Encosta a etiqueta às costas do telemóvel.',
  'prop.keypad': 'Teclado',
  'prop.keypad_hide': 'Esconder o teclado',
  'prop.phase_loading': 'a carregar',
  'prop.phase_ready': 'pronto a começar',
  'prop.phase_running': 'a decorrer',
  'prop.phase_paused': 'em pausa',
  'prop.phase_ended': 'terminado',
  'prop.phase_halted': 'parado por erro',
  'prop.phase_failed': 'não arrancou',
  'prop.notification_title': 'Atalaia: {mode}',
  'prop.notification_running': 'Jogo a decorrer',
  'prop.notification_left': 'Faltam {time}',

  // Preparar o jogo
  'setup.title': 'Novo jogo',
  'setup.joined': 'Jogo do controlador',
  'setup.join_info':
      'Jogo {game}, este dispositivo é o n.º {node}, canal {mhz} MHz.',
  'setup.mode': 'Modo de jogo',
  'setup.with': 'Com {mode}',
  'setup.role': 'Papel no modo',
  'setup.teams': 'Equipas',
  'setup.params': 'Parâmetros do modo',
  'setup.any_team': 'Todas as equipas',
  'setup.length': 'Duração',
  'setup.minutes': 'Minutos',
  'setup.minutes_hint': '0 = sem limite. No fim, o jogo termina sozinho.',
  'setup.prepare': 'Preparar o jogo',
  'setup.missing':
      'Falta a este telemóvel: {caps}. Liga um módulo de E/S que o tenha.',
  'setup.needs_controller':
      'Este modo conta pontos com várias caixas através do controlador de '
      'campo. Sozinho, este dispositivo só faz a parte dele.',
  'setup.unknown_mode': 'Este dispositivo não tem o modo deste jogo.',
  'setup.unknown_role': 'O modo deste jogo não tem esse papel.',

  // Entrar num jogo
  'join.intro':
      'Lê o código QR de entrada na consola da organização, encosta o '
      'cartão de entrada, ou cola o texto atalaia:join:….',
  'join.scan': 'Ler o código QR',
  'join.scan_hint': 'Aponta para o código QR de entrada.',
  'join.card': 'Cartão de entrada (NFC)',
  'join.card_ready': 'Encosta o cartão às costas do telemóvel.',
  'join.text': 'Texto de entrada',
  'join.use_text': 'Usar este texto',
  'join.warning':
      'O cartão e o código levam a chave do jogo: mostra-os só a quem monta o '
      'campo.',
  'join.no_key': 'Primeiro define a chave de entrada do campo nas definições.',
  'join.no_camera': 'Não há câmara disponível para ler o código.',
  'join.bad_text': 'Isto não é um código de entrada válido.',
  'join.not_a_card': 'Este cartão não tem dados de entrada.',
  'join.other_field':
      'Este código é de outro campo (a chave de entrada não confere).',
  'join.bad_body': 'Os dados de entrada estão estragados.',
  'join.for_controller':
      'Este código é para um controlador de reserva, não para um dispositivo.',
  'nfc.off': 'O NFC está desligado: liga-o nas definições do telemóvel.',
  'nfc.none': 'Este telemóvel não tem NFC.',

  // Módulo de E/S
  'pod.title': 'Módulo de E/S',
  'pod.intro':
      'Um módulo de E/S empresta botões grandes, luzes, sirene, leitor NFC e '
      'rádio LoRa ao telemóvel, por USB (de preferência) ou Bluetooth.',
  'pod.none': 'Nenhum módulo ligado: o jogo usa só o telemóvel.',
  'pod.link': 'Ligar um módulo',
  'pod.find': 'Procurar módulos',
  'pod.found_none': 'Nenhum módulo encontrado.',
  'pod.linked': 'Módulo ligado por {kind}: firmware {fw}, {n} capacidades.',
  'pod.open_failed': 'Não foi possível abrir a ligação ao módulo.',
  'pod.no_ident': 'O módulo não respondeu.',
  'pod.reconnecting':
      'A ligação ao módulo perdeu-se. A religar (tentativa {n})…',
  'pod.refused':
      'Respondeu outro módulo, por isso a ligação não foi retomada. Liga um módulo outra vez.',
  'pod.unlink': 'Desligar o módulo',

  // Capacidades
  'cap.team_input': 'botões das equipas',
  'cap.keypad': 'teclado',
  'cap.display': 'ecrã',
  'cap.team_display': 'cor da equipa',
  'cap.led': 'luzes',
  'cap.audio': 'som',
  'cap.haptic': 'vibração',
  'cap.nfc': 'NFC',
  'cap.gps': 'GPS',
  'cap.imu': 'acelerómetro',
  'cap.qr_scanner': 'leitor de QR',
  'cap.button': 'botões',
  'cap.lora': 'rádio LoRa',

  // Equipas
  'team.red': 'vermelha',
  'team.blue': 'azul',
  'team.green': 'verde',
  'team.yellow': 'amarela',
  'team.orange': 'laranja',
  'team.purple': 'roxa',

  // Participante
  'player.intro':
      'Liga-te ao controlador de campo: lê o código QR do marcador ou escreve '
      'o endereço e o código de acesso que a organização te deu.',
  'player.scan': 'Ler o código QR do marcador',
  'player.scan_hint': 'Aponta para o código QR do marcador.',
  'player.by_hand': 'Ou escreve',
  'player.address': 'Endereço do controlador',
  'player.code': 'Código de acesso',
  'player.connect': 'Ligar',
  'code.is_poster':
      'Isto é o cartaz de check-in de um campo. Usa-o em Participante > '
      'Check-in no campo.',
  'code.is_join_card':
      'Isto é um código de entrada para um dispositivo de jogo. Usa-o em '
      'Dispositivo de jogo > Entrar num jogo.',
  'code.is_site_link':
      'Isto é uma ligação às inscrições online de um campo. Usa-a em '
      'Participante > Inscrições online.',
  'code.is_scoreboard':
      'Isto é a ligação do marcador de um jogo. Usa-a em Participante > '
      'Seguir um jogo sem check-in.',
  'player.bad_link': 'Falta o endereço ou o código de acesso.',
  'player.link_unreachable':
      'O controlador não responde. Estás ligado à rede Wi-Fi do campo?',
  'player.link_mismatch':
      'O controlador que responde não é aquele para o qual este código foi feito. Não continues e avisa a organização.',
  'player.link_not_controller':
      'Quem responde neste endereço não é um controlador de campo.',
  'player.connecting': 'A ligar ao controlador de campo…',
  'player.offline': 'Sem ligação. A voltar a ligar…',
  'player.denied': 'O código de acesso não foi aceite.',
  'player.no_game': 'Ainda não há jogo a decorrer.',
  'player.left': 'para o fim',
  'player.score': 'Pontuação',
  'player.my_team': 'a tua equipa',
  'player.pick_team': 'Toca na tua equipa para a destacar.',
  'player.eliminated': 'eliminada',
  'player.lives_left': '{n} vidas',
  'player.objectives': 'Objetivos',
  'player.node': 'Caixa {n}',
  'player.held_by': 'Da equipa {team}',
  'player.held_by_none': 'De ninguém',
  'player.active_box': 'Caixa ativa: {zone}',
  'player.active_box_tag': 'ATIVA',
  'player.scenario': 'Objetivos do cenário',
  'player.objective_waiting': 'Começa com o jogo',
  'player.objective_active': 'Em curso',
  'player.objective_done': 'Cumprido pela equipa {team}',
  'player.objective_done_no_team': 'Cumprido',
  'player.objective_failed': 'Falhado',
  'player.objective_failed_captured': 'Falhado: tomado por outra equipa',
  'player.objective_failed_defused': 'Falhado: a bomba foi desarmada',
  'player.objective_failed_time': 'Falhado: o tempo acabou',
  'player.objective_failed_blocked': 'Falhado: um objetivo anterior falhou',
  'player.objective_failed_lives': 'Falhado: sem vidas suficientes',
  'player.objective_for_team': 'Para a equipa {team}',
  'player.objective_for_squad': 'Para a equipa {team}, squad {squad}',
  'player.objective_points': '+{n}',
  'player.lives': 'Vidas',
  'player.events': 'O que aconteceu',
  'player.no_events': 'Ainda nada.',
  'player.message': 'Organização: {text}',
  'player.ended': 'O jogo terminou.',
  'player.tie': 'Empate',
  'player.winner': 'Vence a equipa {team}',
  'state.ready': 'pronto',
  'state.running': 'a decorrer',
  'state.paused': 'em pausa',
  'state.ended': 'terminado',

  // Acontecimentos
  'event.game.start': 'O jogo começou',
  'event.game.pause': 'Jogo em pausa',
  'event.game.resume': 'O jogo recomeçou',
  'event.game.end': 'O jogo terminou',
  'event.zone.captured': 'A equipa {team} capturou {zone}',
  'event.zone.neutralized': '{zone} ficou livre',
  'event.bomb.armed': 'Bomba armada pela equipa {team} ({fuse} s)',
  'event.bomb.defused': 'Bomba desarmada pela equipa {team}',
  'event.bomb.exploded': 'A bomba explodiu',
  'event.bomb.reset': 'A bomba voltou ao início',
  'event.score.delta': 'Pontos para a equipa {team}: {amount}',
  'event.code.used': 'A equipa {team} usou um código',
  'event.player.respawn': '{player} voltou ao jogo ({lives} vidas)',
  'event.player.checkin': '{player} registou presença',
  'event.kill.confirmed': 'Baixa confirmada pela equipa {team} ({player})',
  'event.kill.denied': 'A equipa {team} recuperou a etiqueta de {player}',
  'event.team.eliminated': 'A equipa {team} ficou sem vidas',
  'event.holdall.scoring_start': 'A equipa {team} tem todas as zonas',
  'event.holdall.scoring_stop': 'A equipa {team} perdeu uma zona',
  'event.laststand.countdown_start': 'Último elemento: começou a contagem',
  'event.laststand.countdown_cancel': 'Último elemento: contagem cancelada',
  'event.laststand.defeated': 'Último elemento: a defesa caiu',
  'event.gm.message': 'Organização: {text}',
  'event.visibility.granted': 'A equipa {team} vê o campo',
  'event.medic.heal':
      '{player} recebeu tratamento (ligaduras no kit: {remaining})',
  'event.medic.empty': 'Um kit de ligaduras ficou vazio',
  'event.hacking.solved': 'A equipa {team} hackeou um terminal',
  'event.hacking.solved.no_team': 'Um terminal foi hackeado',
  'event.vip.extracted': 'A equipa {team} chegou à zona de extração',
  'event.money.collected': '{player} recolheu {amount} de dinheiro',
  'event.money.deposited': '{player} depositou {amount} para a equipa {team}',
  'event.progressive.activated':
      'A caixa {zone} está ativa (n.º {step}): é a única que pode ser capturada',
  'event.progressive.completed':
      'A equipa {team} completou a caixa {zone} (n.º {step})',
  'event.scenario.started': 'O cenário começou',
  'event.scenario.objective.completed': 'A equipa {team} cumpriu um objetivo',
  'event.scenario.objective.completed.no_team': 'Um objetivo foi cumprido',
  'event.scenario.objective.failed': 'A equipa {team} falhou um objetivo',
  'event.scenario.objective.failed.no_team': 'Um objetivo falhou',
  'event.scenario.objective.revealed': 'Novo objetivo para a equipa {team}',
  'event.scenario.objective.revealed.no_team': 'Novo objetivo',
  'event.scenario.objective.completed.named':
      'A equipa {team} cumpriu: {objective}',
  'event.scenario.objective.completed.named.no_team': 'Cumprido: {objective}',
  'event.scenario.objective.failed.named':
      'A equipa {team} falhou: {objective}',
  'event.scenario.objective.failed.named.no_team': 'Falhado: {objective}',
  'event.scenario.objective.revealed.named':
      'Novo objetivo para a equipa {team}: {objective}',
  'event.scenario.objective.revealed.named.no_team':
      'Novo objetivo: {objective}',
  'event.scenario.objective.revealed.leader':
      'O teu líder de squad tem novas ordens',
  'player.leader_orders': 'Ordens para o teu squad: o líder de squad passa-as',
  'event.chrono.violation': 'Réplica acima do limite',
  'event.node.tamper': 'Alguém mexeu numa caixa ({reason})',

  // Organização
  'gm.intro':
      'A consola da organização do controlador de campo. Escreve o endereço '
      'do controlador; a consola pede o código de acesso.',
  'gm.address': 'Endereço da consola',
  'gm.open': 'Abrir a consola',
  'gm.bad_url': 'Este endereço não serve.',
  'gm.change': 'Mudar de endereço',

  // Marshal
  'marshal.no_identity':
      'Para registar medições, o controlador do campo tem de te confirmar '
      'como marshal: faz o check-in no campo com o cartaz e a organização '
      'põe-te na lista. O teu nome e identificador vêm dessa lista e a chave '
      'de assinatura é criada automaticamente.',
  'marshal.identity': 'Quem és',
  'marshal.name': 'Nome do marshal',
  'marshal.id': 'Identificador do marshal',
  'marshal.field_id': 'Identificador do campo',
  'marshal.chrono_id': 'Identificador do cronógrafo',
  'marshal.key': 'Chave de assinatura',
  'marshal.no_key': 'Ainda não tens chave: as medições têm de ser assinadas.',
  'marshal.key_id': 'Chave pública {id}…',
  'marshal.new_key': 'Nova chave',
  'marshal.new_key_body':
      'As medições antigas continuam assinadas com a chave antiga; as novas '
      'passam a ser assinadas com a nova.',
  'marshal.records': 'Medições guardadas',
  'marshal.readings':
      '{n} medições neste telemóvel. Guardam-se 365 dias e depois são '
      'apagadas.',
  'marshal.erase': 'Apagar as medições de alguém',
  'marshal.erase_do': 'Apagar',
  'marshal.checking': 'A perguntar ao controlador do campo…',
  'marshal.you_are': 'O teu identificador de marshal é {id} ({name})',
  'marshal.id_from_gm':
      'O identificador e o nome vêm da lista de marshals da organização; o controlador do campo confirmou-os.',
  'marshal.not_listed':
      'O controlador do campo não te tem na lista de marshals. Pede à organização para te acrescentar como marshal.',
  'marshal.revoked':
      'A organização retirou-te da lista de marshals, por isso este telemóvel já não é de marshal neste campo. As {n} série(s) por enviar ficam neste telemóvel e podem ser enviadas se a organização te voltar a acrescentar.',
  'marshal.offline_never':
      'Sem ligação ao controlador do campo, e este telemóvel ainda não foi confirmado como marshal aqui. Liga-te uma vez à rede do campo e pergunta outra vez.',
  'marshal.offline_expired':
      'Sem ligação ao controlador do campo, e a confirmação de {at} caducou. Liga-te à rede do campo e pergunta outra vez.',
  'marshal.offline_ok':
      'Sem ligação: o controlador do campo confirmou-te como marshal {id} em {at}. Vale até {until}; depois disso, liga-te à rede do campo para confirmar outra vez.',
  'marshal.retry': 'Perguntar outra vez',
  'marshal.expired_now':
      'A confirmação do controlador do campo caducou: pergunta outra vez antes de registar.',

  // Cronógrafo
  'chrono.title': 'Cronógrafo',
  'chrono.hint':
      'Check-in e verificações durante o jogo, com o limite do campo.',
  'chrono.template': 'Limites do campo',
  'chrono.template_set': 'Definidos pelo controlador do campo.',
  'chrono.template_local':
      'O controlador do campo julga com a sua própria lista, e é o veredicto '
      'dele que conta. Esta lista serve só para a pré-visualização neste '
      'telemóvel.',
  'chrono.template_unknown':
      'O controlador do campo usa os limites «{name}», que esta app não tem. '
      'O veredicto dele é o que conta; os valores aqui são só uma indicação.',
  'limits.portugal': 'Portugal',
  'limits.uk': 'Reino Unido',
  'limits.germany': 'Alemanha',
  'limits.generic_cqb': 'CQB genérico',
  'replica.class_rifle': 'Espingarda',
  'replica.class_dmr': 'DMR',
  'replica.class_sniper': 'Sniper',
  'replica.class_cqb': 'CQB',
  'replica.class_semi': 'Semiautomática',
  'chrono.unverified':
      'Os limites «{name}» não estão verificados: vêm da pesquisa do '
      'projeto, não de uma fonte oficial. Confirma-os com as regras atuais '
      'antes de os usares.',
  'chrono.checkin': 'Check-in',
  'chrono.spotcheck': 'Verificação',
  'chrono.replica': 'Réplica',
  'chrono.replica_nfc': 'Ou encosta a etiqueta da réplica.',
  'chrono.unknown_tag': 'Esta etiqueta não está no registo de réplicas.',
  'chrono.no_class': 'Os limites do campo não têm a classe «{class}».',
  'chrono.limit': 'Limite: {j} J ({fps} fps com 0,20 g)',
  'chrono.bb': 'Peso da BB',
  'chrono.velocity': 'Velocidade',
  'chrono.energy': 'Energia: {j} J',
  'chrono.record': 'Registar o disparo',
  'chrono.new_series': 'Nova série',
  'chrono.pass': 'PASSA',
  'chrono.warn': 'ATENÇÃO',
  'chrono.fail': 'CHUMBA',
  'chrono.highest': 'Mais alta: {j} J · limite {limit} J',
  'chrono.vs_checkin': 'Na entrada: {j} J (+{pct}% de tolerância)',

  // Réplicas
  'replica.title': 'Registo de réplicas',
  'replica.add': 'Registar réplica',
  'replica.none': 'Ainda não há réplicas registadas.',
  'replica.count': '{n} réplicas registadas',
  'replica.owner': 'Identificador de quem joga',
  'replica.type': 'Tipo',
  'replica.class': 'Classe',
  'replica.model': 'Marca e modelo',
  'replica.tag': 'Etiqueta da réplica',
  'replica.tap_tag': 'Encosta a etiqueta NFC da réplica, ou lê a etiqueta QR.',
  'replica.tag_read': 'Etiqueta: {uid}',
  'replica.scan': 'Ler etiqueta QR',
  'replica.scan_hint': 'Aponta para a etiqueta QR da réplica.',
  'replica.needs_tag': 'Falta a classe ou a etiqueta da réplica.',
  'replica.type_aeg': 'AEG',
  'replica.type_gbb': 'GBB',
  'replica.type_hpa': 'HPA',
  'replica.type_bolt_action': 'Ferrolho',
  'replica.type_dmr': 'DMR',
  'replica.type_sniper': 'Sniper',
  'replica.type_pistol': 'Pistola',
  'replica.type_shotgun': 'Caçadeira',

  // Etiquetas
  'tags.title': 'Etiquetas de quem joga',
  'tags.hint': 'Escrever as etiquetas NFC assinadas para um jogo.',
  'tags.intro':
      'As etiquetas são assinadas pelo controlador do campo, que guarda a '
      'chave do jogo: nunca precisas da chave de entrada do campo. Liga-te '
      'ao Wi-Fi do campo, escreve quem joga e encosta uma etiqueta virgem ao '
      'telemóvel.',
  'tags.for_game': 'Jogo: {game}',
  'tags.loading': 'A perguntar ao controlador do campo…',
  'tags.offline':
      'Não é possível falar com o controlador do campo: liga-te ao Wi-Fi do '
      'campo e tenta outra vez.',
  'tags.not_marshal':
      'O controlador do campo diz que não és marshal aqui: fala com a '
      'organização.',
  'tags.session': 'O teu check-in expirou: faz o check-in outra vez.',
  'tags.no_key':
      'O jogo não está a decorrer no controlador (terminou, ou perdeu a chave '
      'do jogo), por isso não pode assinar etiquetas.',
  'tags.refused': 'O controlador do campo recusou a etiqueta: {error}',
  'tags.bad_answer':
      'A resposta do controlador não é uma etiqueta válida para este jogador.',
  'tags.player': 'Identificador de quem joga',
  'tags.player_hint': 'Letras, algarismos, - _ e . (até 32), ex.: p-17',
  'tags.bad_player': 'O identificador tem 1 a 32 letras, algarismos, -, _ ou .',
  'tags.no_team': 'Sem equipa',
  'tags.write': 'Escrever a etiqueta',
  'tags.hold': 'Encosta a etiqueta às costas do telemóvel…',
  'tags.written': 'Escritas agora',
  'tags.write_not_ndef': 'Esta etiqueta não aceita dados NDEF.',
  'tags.write_read_only': 'Esta etiqueta está bloqueada.',
  'tags.write_too_small': 'A etiqueta é pequena demais.',
  'tags.write_io':
      'A escrita falhou: mantém a etiqueta encostada e tenta outra vez.',
  'tags.write_unavailable': 'Este telemóvel não escreve etiquetas NFC.',

  // Check-in no campo, réplicas por cronografar, posições (fase E)
  'checkin.title': 'Check-in no campo',
  'checkin.intro':
      'Lê o cartaz de check-in do campo com a câmara (ou cola o texto dele). O telemóvel liga-se ao controlador do campo pela rede Wi-Fi do campo; não precisa de internet.',
  'checkin.scan': 'Ler o cartaz',
  'checkin.scan_hint': 'Aponta para o código QR do cartaz de check-in',
  'checkin.by_text': 'Ou cola o texto do cartaz',
  'checkin.text_hint': 'atalaia:checkin:…',
  'checkin.use_text': 'Usar este texto',
  'checkin.bad_poster':
      'Este cartaz de check-in não se consegue ler. Pede outro à organização.',
  'checkin.not_poster': 'Isto não é um cartaz de check-in do Atalaia.',
  // Why the field controller did not answer (check-R5)
  'diag.title': 'Detalhes',
  'diag.timeout': 'sem resposta a tempo',
  'diag.refused': 'ligação recusada',
  'diag.unreachable': 'sem caminho até ao endereço',
  'diag.tls': 'certificado não aceite',
  'diag.http': 'HTTP {status}',
  'diag.other': 'erro de ligação',
  'diag.line': '{kind} · {url} · {time}',
  'checkin.unreachable':
      'O controlador do campo não responde. Estás ligado à rede Wi-Fi do campo?',
  'checkin.join_wifi':
      'O controlador do campo não responde: liga-te à rede Wi-Fi «{ssid}» e tenta outra vez.',
  'checkin.mismatch':
      'O controlador que responde não é o do cartaz (cartaz {poster}, controlador {got}). Não continues e avisa a organização.',
  'checkin.not_controller':
      'Quem responde neste endereço não é um controlador de campo.',
  'checkin.changed':
      'Este campo já foi confiado com outro certificado ({old}); o cartaz mostra {new}. Se a organização confirmar que o controlador mudou, esquece o campo e lê o cartaz outra vez.',
  'checkin.forget_field': 'Esquecer este campo',
  'checkin.error': 'O controlador recusou: {error}',
  'checkin.offline':
      'Sem ligação ao controlador do campo: tenta outra vez quando estiveres na rede do campo.',
  'checkin.expired': 'Este check-in já não é válido: faz o check-in outra vez.',
  'checkin.connecting': 'A ligar ao controlador do campo…',
  'checkin.notice_title': 'Os teus dados em {field}',
  'checkin.notice_ok': 'Li e quero continuar',
  'checkin.trusted': 'Certificado do campo {ca}',
  'checkin.no_games': 'Não há nenhum jogo aberto para check-in neste campo.',
  'checkin.game': 'Jogo',
  'checkin.for_game': 'Jogo: {game}',
  'checkin.name': 'Nome ou alcunha',
  'checkin.name_hint':
      'É o que a organização e os marshals veem; quem joga contigo não.',
  'checkin.federation_required': 'Número de federado ({label})',
  'checkin.federation_optional': 'Número de federado ({label}, opcional)',
  'checkin.federation_hint':
      'A organização confere o cartão à entrada; a app não o verifica.',
  'checkin.need_name': 'Escreve um nome ou uma alcunha.',
  'checkin.need_federation': 'Este campo pede o número de federado ({label}).',
  'checkin.pick_game': 'Escolhe o jogo.',
  'checkin.team_pref': 'Equipa preferida',
  'checkin.any_team': 'Qualquer uma',
  'checkin.bring': 'Réplicas que trazes',
  'checkin.submit': 'Fazer o check-in',
  'checkin.status_title': 'O meu check-in',
  'checkin.status.pending': 'À espera de confirmação na mesa da organização.',
  'checkin.status.checked_in': 'Check-in feito.',
  'checkin.status.left': 'Saíste deste jogo.',
  'checkin.status.removed': 'A organização retirou este check-in.',
  'checkin.role.player': 'Jogador/a',
  'checkin.role.squad_leader': 'Líder de squad',
  'checkin.role.vip': 'VIP',
  'checkin.role.marshal': 'Marshal',
  'checkin.role.gm': 'Organização',
  'checkin.role.spectator': 'Espectador/a',
  'checkin.my_declaration': 'As minhas réplicas neste jogo',
  'checkin.no_replicas': 'Ainda não declaraste nenhuma réplica.',
  'checkin.declare': 'Escolher as réplicas',
  'checkin.follow': 'Seguir o jogo',
  'checkin.leave': 'Sair do jogo',
  'checkin.leave_body':
      'O teu nome e o número de federado são apagados deste jogo. As réplicas já cronografadas ficam registadas.',
  'checkin.left': 'Saíste do jogo; os teus dados foram apagados.',
  'chrono_state.pending': 'por cronografar',
  'chrono_state.passed': 'aprovada',
  'chrono_state.refused': 'recusada',
  'chrono_state.withdrawn': 'retirada',
  'chrono_state.refused_today': 'recusada hoje',
  'declare.title': 'As réplicas deste jogo',
  'declare.intro':
      'Escolhe as réplicas que vais usar neste jogo (até {max}). Leva-as aos marshals para a cronografagem.',
  'declare.none': 'Ainda não tens réplicas: junta as tuas.',
  'declare.add': 'Juntar uma réplica',
  'declare.type': 'Tipo',
  'declare.class': 'Classe',
  'declare.make': 'Marca e modelo (opcional)',
  'declare.save': 'Guardar',
  'declare.saved': 'Guardado: a organização e os marshals já as veem.',
  'declare.locked':
      'Uma réplica já cronografada fica declarada: fala com um marshal para a mudar.',
  'queue.title': 'Réplicas por cronografar',
  'queue.hint':
      'A lista do campo: quem declarou réplicas que ainda não passaram no cronógrafo.',
  'queue.check_in_first':
      'Primeiro faz o check-in no campo com o cartaz; depois a organização dá-te o papel de marshal.',
  'queue.not_marshal': 'Esta lista é só para marshals e para a organização.',
  'queue.counts':
      'Por cronografar: {pending} · aprovadas: {passed} · recusadas: {refused}',
  'queue.scan': 'Ler a etiqueta de uma réplica',
  'queue.scan_hint': 'Aponta para a etiqueta QR da réplica',
  'queue.not_found':
      'Esta réplica não está declarada neste jogo: escolhe a declaração do jogador ou da jogadora.',
  'queue.refresh': 'Atualizar',
  'queue.empty': 'Ninguém declarou réplicas ainda.',
  'queue.manual': 'Check-in à mão',
  'queue.manual_do': 'Fazer o check-in',
  'queue.manual_done': 'Check-in feito: {id}',
  'queue.send_pending': 'Enviar {n} série(s) por enviar',
  'queue.send_failed': '{n} série(s) não foram aceites; ficam neste telemóvel.',
  'queue.held':
      '{n} série(s) não foram aceites porque o controlador não te tem na lista de marshals; ficam neste telemóvel.',
  'queue.waiting_confirmation': 'à espera de confirmação',
  'queue.sticker_title': 'Usar um autocolante NFC?',
  'queue.sticker_body':
      'Encostar o autocolante NFC da réplica ao telemóvel para a registar por ele, ou usar a etiqueta QR impressa.',
  'queue.sticker_qr': 'Usar a etiqueta QR',
  'queue.sticker_taken': 'Este autocolante já está registado noutra réplica.',
  'queue.unregistered': 'ainda sem registo',
  'label.title': 'Etiqueta da réplica',
  'label.show': 'Mostrar etiqueta',
  'label.share': 'Partilhar / imprimir etiqueta',
  'label.share_all': 'Partilhar / imprimir todas as etiquetas',
  'label.share_title': 'Etiquetas de réplicas',
  'label.hint':
      'Cola esta etiqueta na réplica. O marshal lê-a para encontrar a réplica na lista do cronógrafo. Só tem este código, nada sobre ti. Imprime-se a 30 × 30 mm; várias etiquetas cabem numa folha A4.',
  'label.share_unavailable':
      'Este telemóvel não consegue passar um ficheiro à partilha. Usa antes Mostrar etiqueta.',
  'label.share_failed': 'A partilha não abriu.',
  'label.none_yet':
      'A etiqueta aparece aqui depois de declarares esta réplica num jogo.',
  'chrono.send': 'Enviar ao controlador',
  'chrono.sent_pass': 'Enviado: aprovada.',
  'chrono.sent_fail': 'Enviado: recusada.',
  'chrono.sent_warn': 'Enviado: aviso.',
  'chrono.sent_unjudged': 'Enviado: sem classe para comparar.',
  'chrono.sent_null': 'Enviado.',
  'chrono.send_failed':
      'Não foi enviado: {error}. Fica neste telemóvel para enviar depois.',
  'player.checkin': 'Check-in no campo',
  'player.watch': 'Seguir um jogo sem check-in',
  'player.continue': 'Continuar: {game}',
  'player.me': 'Tu: {role}, {team}',
  'player.no_team': 'ainda sem equipa',
  'player.positions': 'Posições que vês: {n}',
  'player.share': 'Partilhar a minha posição',
  'player.share_hint':
      'Só durante o jogo; o controlador decide quem a vê. A organização e os marshals veem-na nos seus dispositivos ATAK.',
  'player.share_on': 'A partilhar: {n} posição(ões) enviada(s)',
  'player.share_stopped':
      'A partilha parou: o jogo terminou ou o check-in mudou.',
  'player.no_location': 'Este telemóvel não tem localização.',
  'player.location_denied': 'Sem autorização para a localização.',
  'player.location_denied_ios':
      'Sem autorização para a localização. Permite-a em Definições > Atalaia > Localização (Ao Usar a Aplicação) e confirma que os Serviços de Localização estão ligados.',
  'player.share_ios_note':
      'No iPhone a posição só é partilhada enquanto o Atalaia está aberto no ecrã: pára se mudares de aplicação ou bloqueares o telemóvel, e continua quando voltas.',
  'player.sharing_title': 'Atalaia: a partilhar a posição',
  'player.sharing_text': 'Durante o jogo',
  // O aviso de fora do campo (decisões MF-31 a MF-40)
  'player.out_title': 'Fora do campo',
  'player.out_text': 'Saíste do limite do campo. Volta para dentro.',
  'player.bounds_watch': 'Este telemóvel vibra se saíres do limite do campo.',
  'prop.link.connecting': 'A ligar ao controlador…',
  'prop.link.linked': 'Ligado ao controlador pela rede Wi-Fi',
  'prop.link.refused': 'O controlador recusou este dispositivo (outro jogo?)',
  'prop.link.offline': 'Sem ligação ao controlador: a tentar outra vez…',
  'prop.link.closed': 'Outro dispositivo tomou o lugar deste',
  'prop.radio.configuring': 'A preparar o rádio do módulo…',
  'prop.radio.linked': 'O rádio do módulo está no canal do campo',
  'prop.radio.heard': 'Ligado ao controlador pelo rádio do módulo',
  'prop.radio.offline': 'O rádio do módulo não responde: a tentar outra vez…',
  'prop.radio.closed': 'O rádio do módulo está desligado',
  'prop.gm_message': 'Organização: {text}',
  // Balizas interiores (decisões BLE-1 a BLE-9)
  'player.beacons_why_title': 'Posições no interior',
  'player.beacons_why':
      'Este campo tem balizas Bluetooth no interior. Para saber em que divisão estás, o Atalaia pode ouvi-las enquanto partilhas a posição: só as balizas do campo, e envia apenas qual é a mais forte. O Android pede as autorizações de Bluetooth e de localização para isso. Sem elas a tua posição fica só por GPS.',
  'player.beacons_allow': 'Continuar',
  'player.beacons_skip': 'Agora não',
  'player.beacons_on':
      'A ouvir as balizas do campo: no interior a tua posição é a divisão.',
  'player.beacons_skipped':
      'As posições no interior estão desligadas. A posição por GPS continua a ser partilhada.',
  'player.beacons_denied':
      'As posições no interior estão desligadas: sem autorização para o Bluetooth. A posição por GPS continua a ser partilhada.',
  'player.beacons_off':
      'As posições no interior estão desligadas: o Bluetooth está desligado. Liga-o e partilha outra vez.',
  'player.beacons_unavailable':
      'Este telemóvel não consegue ouvir as balizas do campo. A posição por GPS continua a ser partilhada.',
  'player.beacons_ios':
      'No iPhone as balizas interiores do campo ainda não são usadas: a posição é só por GPS.',
  'player.my_room': 'A tua posição: {room}',
  'player.map_title': 'Mapa do campo',
  'player.map_semantics': 'Mapa do campo, {level}: {n} posições',
  'player.map_off_plan': '{n} posições fora desta planta',
  'player.map_level_unknown':
      'Pontos vazios: quem ainda não disse em que piso está.',
  'player.map_level_unknown_short': 'piso desconhecido',
  'player.map_cell': 'A tua quadrícula: {cell}',
  'player.map_you': 'Tu',
  'player.map_player': 'Participante',
  'player.map_player_team': 'Participante de {team}',
  'player.level_n': 'Piso {n}',
  'player.level_title': 'Em que piso estás?',
  'player.level_unknown': 'Não sei',
  'player.level_hint':
      'A tua equipa vê-te nesse piso. O telemóvel não distingue os pisos sozinho.',
  'player.level_beacon': 'O teu piso vem da baliza da sala: {level}.',
  'player.feature.safe_zone': 'Zona segura',
  'player.feature.respawn': 'Respawn',
  'player.feature.hq': 'Quartel-general',
  'player.feature.parking': 'Estacionamento',
  'player.feature.first_aid': 'Primeiros socorros',
  'player.feature.objective': 'Objetivo',
  'player.feature.other': 'Outro',
  'player.feature.boundary': 'Limite do campo',
  'player.share_hint_squads':
      'Só durante o jogo; o controlador decide quem a vê: o teu squad, se o jogo o permitir, e a organização e os marshals nos seus dispositivos ATAK.',
  'checkin.team_squad': '{team} › squad {squad}',
  'branding.logo': 'Logótipo de {name}',
  // Inscrições online no servidor do campo (decisão S16-13)
  'player.site': 'Inscrições online',
  'site.title': 'Inscrições online',
  'site.intro':
      'As inscrições num jogo fazem-se com uma conta no site do campo. '
      'Abre o botão «Fazer a inscrição» da página do jogo, ou cola aqui o '
      'endereço da página do campo ou do jogo.',
  'site.address': 'Endereço da página do campo ou do jogo',
  'site.open': 'Abrir',
  'site.bad_address':
      'Isto não é o endereço de uma página de campo ou de jogo (https://…/f/…).',
  'site.confirm_text':
      'Vais entrar com a tua conta em {host}. Só continues se for o site do '
      'campo onde vais jogar: quem fez a ligação pode ter escrito outro site.',
  'site.confirm': 'É este o site, continuar',
  'site.login_at': 'Entrar em {host}',
  'site.login_hint':
      'Com a conta que criaste neste site. A app guarda a sessão neste '
      'telemóvel; a palavra-passe não fica guardada.',
  'site.username': 'Nome de utilizador',
  'site.password': 'Palavra-passe',
  'site.login': 'Entrar',
  'site.need_login': 'Escreve o nome de utilizador e a palavra-passe.',
  'site.totp_text':
      'Esta conta tem verificação em dois passos: escreve o código da tua '
      'app de autenticação.',
  'site.code': 'Código de 6 algarismos',
  'site.logged_in': 'Com a conta {user} em {host}',
  'site.logout': 'Sair da conta',
  'site.games': 'Jogos',
  'site.no_games': 'Este campo não tem jogos publicados para os próximos dias.',
  'site.game_gone': 'Esse jogo já não está publicado ou já terminou.',
  'site.cancelled': 'Cancelado',
  'site.cancelled_reason': 'Este jogo foi cancelado: {reason}',
  'site.open_until': 'Inscrições abertas até {when}',
  'site.left': '{n} lugares',
  'site.opens': 'As inscrições abrem a {when}',
  'site.full': 'Esgotado',
  'site.closed': 'Inscrições fechadas',
  'site.no_online': 'Sem inscrição online: fala com a organização do campo.',
  'site.reg.registered': 'Tens inscrição neste jogo.',
  'site.reg.checked_in': 'Fizeste o check-in neste jogo.',
  'site.reg.no_show': 'Não compareceste a este jogo.',
  'site.reg.cancelled': 'Cancelaste a inscrição.',
  'site.form': 'Inscrição',
  'site.form_change': 'Alterar a inscrição',
  'site.name_hint': 'O nome que a organização e os marshals veem neste jogo.',
  'site.replicas': 'Réplicas que vais usar (até {n})',
  'site.class_not_here': '{class}: este campo não tem esta classe',
  'site.too_many': 'Este campo aceita até {n} réplicas por pessoa.',
  'site.register': 'Fazer a inscrição',
  'site.save': 'Guardar as alterações',
  'site.changed': 'Inscrição alterada.',
  'site.cancel_reg': 'Cancelar a inscrição',
  'site.cancel_title': 'Cancelar a inscrição?',
  'site.cancel_text':
      'Deixas de ter lugar em {game} e o bilhete de check-in deixa de valer.',
  'site.cancel_yes': 'Cancelar a inscrição',
  'site.data_note':
      'O campo recebe o nome escolhido para o jogo, a preferência de equipa, '
      'o número de federado (se o jogo o pedir) e as réplicas declaradas, e '
      'apaga-os 30 dias depois do jogo.',
  'site.show_ticket': 'Mostrar o bilhete de check-in',
  'site.no_ticket_here':
      'O bilhete desta inscrição não está neste telemóvel. Pede um novo: o '
      'antigo deixa de valer.',
  'site.new_ticket': 'Pedir um bilhete novo',
  'site.ticket': 'Bilhete de check-in',
  'site.ticket_text':
      'No campo, mostra este código a um marshal, ou faz o check-in na app '
      'com «Check-in no campo» e escolhe esta inscrição. O texto do bilhete:',
  'site.copy': 'Copiar o texto',
  'site.copied': 'Copiado.',
  'site.ticket_secret':
      'Quem tiver este bilhete pode fazer o check-in no teu lugar: não o '
      'partilhes.',
  'site.my_tickets': 'Os meus bilhetes',
  'site.no_tickets': 'Ainda não há bilhetes neste telemóvel.',
  'site.claim': 'Usar o meu ID deste telemóvel',
  'site.claim_text':
      'Se já fizeste check-in em {field} com este telemóvel, a conta pode '
      'ficar com o mesmo ID de participante (as tuas réplicas e '
      'cronografagens). O controlador do campo confirma-o na próxima '
      'sincronização.',
  'site.claim_pick': 'Os IDs deste telemóvel',
  'site.claim_at': 'No controlador {field}',
  'site.claim_none': 'Este telemóvel ainda não fez check-in em nenhum campo.',
  'site.claim_send': 'Pedir este ID',
  'site.claim_linked': 'A conta já tem o ID {id} neste campo.',
  'site.claim.pending':
      'Pedido enviado: à espera da confirmação do controlador do campo.',
  'site.claim.confirmed': 'Confirmado.',
  'site.claim.refused':
      'O controlador do campo não confirmou esse ID (outro telemóvel, ou um '
      'check-in feito à mão).',
  'site.error': 'O site recusou: {error}',

  // Histórico de jogos
  'history.title': 'Histórico de jogos',
  'history.reload': 'Atualizar',
  'history.intro':
      'Os jogos em que participaste, segundo os registos do site dos campos '
      'onde esta conta tem um ID de jogador: as pontuações e os teus '
      'próprios eventos.',
  'history.none':
      'Ainda não há jogos. Um jogo aparece aqui quando o campo o envia para '
      'o site.',
  'history.unnamed': 'Jogo',
  'history.at': 'No campo {field}',
  'history.state.ready': 'Por começar',
  'history.state.running': 'A decorrer',
  'history.state.paused': 'Em pausa',
  'history.state.ended': 'Terminado',
  'history.winner': 'Vencedora: {team}',
  'history.no_winner': 'Sem vencedora (empate, ou sem pontos).',
  'history.scores': 'Pontuações',
  'history.no_scores': 'O site não tem pontuações deste jogo.',
  'history.events': 'Os teus eventos',
  'history.no_events': 'O site não tem eventos teus neste jogo.',
  'history.registered': 'Fizeste o check-in neste jogo.',
  'history.you': 'tu',
  'site.err.offline': 'Sem ligação ao site. Tenta outra vez daqui a pouco.',
  'site.err.login_required': 'A sessão terminou: entra outra vez.',
  'site.err.invalid_credentials':
      'Nome de utilizador ou palavra-passe errados.',
  'site.err.invalid_code': 'Código errado. Tenta o código seguinte.',
  'site.err.invalid_totp_session':
      'O passo do código expirou: escreve outra vez a palavra-passe.',
  'site.err.too_many_attempts': 'Demasiadas tentativas: espera um pouco.',
  'site.err.field_not_found': 'Este site não tem esse campo.',
  'site.err.http_404':
      'Este site não tem inscrições online (versão antiga do servidor?).',
  'site.err.scheduled_game_not_found': 'Esse jogo já não existe.',
  'site.err.registration_not_found': 'Essa inscrição já não existe.',
  'site.err.registration_closed': 'As inscrições deste jogo estão fechadas.',
  'site.err.game_full': 'Este jogo está esgotado.',
  'site.err.already_registered': 'Já tens inscrição neste jogo.',
  'site.err.not_registered': 'Esta inscrição já não está ativa.',
  'site.err.game_started': 'O jogo já começou.',
  'site.err.federation_number_required': 'Este jogo pede o número de federado.',
  'site.err.display_name_invalid': 'O nome tem de ter 1 a 32 caracteres.',
  'site.err.team_preference_invalid': 'Essa equipa não está neste jogo.',
  'site.err.too_many_replicas': 'Réplicas a mais para este campo.',
  'site.err.replica_class_invalid':
      'Uma das réplicas tem uma classe que este campo não tem.',
  'site.err.replicas_not_asked': 'Este jogo não pede réplicas na inscrição.',
  'site.err.player_id_exists':
      'A conta já tem um ID de participante neste campo.',
  'site.err.player_id_taken': 'Esse ID já é de outra conta.',
  'site.err.player_secret_invalid': 'O segredo deste ID não é válido.',
  'checkin.registered': 'Inscrição online',
  'checkin.no_registration': 'Sem inscrição (entrada no dia)',
  'checkin.registered_hint':
      'Se te inscreveste no site do campo, escolhe a inscrição: o bilhete vai '
      'com o check-in.',
  'checkin.ticket_other_id':
      'Este telemóvel já tem outro ID neste campo. Usa «Usar o meu ID deste '
      'telemóvel» nas inscrições online, ou faz o check-in sem a inscrição.',

  // Controlador de campo (fatia S6 da PE24)
  'ctl.intro':
      'Este telemóvel faz de controlador de campo de um jogo pequeno, sem '
      'Raspberry Pi: corre o jogo, serve a consola da organização, o '
      'check-in e o marcador na rede Wi-Fi do campo, e fala com as caixas '
      'através de um módulo de E/S. Continua a correr com o ecrã apagado.',
  'ctl.refresh': 'Atualizar',
  'ctl.phase_stopped': 'Parado',
  'ctl.phase_starting': 'A arrancar…',
  'ctl.phase_running': 'A funcionar',
  'ctl.phase_stopping': 'A parar…',
  'ctl.stopped_hint':
      'Os jogos ficam guardados: ao arrancar outra vez, o jogo em curso '
      'continua.',
  'ctl.no_game': 'Sem jogo em curso. Cria um na consola.',
  'ctl.game': '{name}: {state}',
  'ctl.game_ready': 'pronto a começar',
  'ctl.game_running': 'a decorrer',
  'ctl.game_paused': 'em pausa',
  'ctl.game_ended': 'terminado',
  'ctl.clients':
      'Ligações: {stream} à consola ou ao marcador, {mqtt} por MQTT, {props} '
      'de dispositivos de jogo por Wi-Fi.',
  'ctl.start': 'Arrancar o controlador',
  'ctl.stop': 'Parar o controlador',
  'ctl.error_storage':
      'Este telemóvel não deu uma pasta privada à app: o controlador não '
      'pode guardar os jogos.',
  'ctl.error_start': 'O controlador não arrancou.',
  'ctl.error_ended': 'O controlador parou sozinho.',
  'ctl.no_foreground':
      'O Android não deixou abrir a notificação do controlador: com o ecrã '
      'apagado, pode parar. Deixa a app aberta ou dá-lhe a permissão de '
      'notificações.',
  'ctl.battery':
      'A otimização da bateria pode parar o controlador a meio de um jogo.',
  'ctl.battery_ask': 'Pedir a exceção',
  'ctl.network': 'Rede do campo',
  'ctl.open': 'Aberto na rede Wi-Fi do campo',
  'ctl.open_on':
      'Telemóveis, computadores e dispositivos de jogo ligam-se por HTTPS '
      '(porta 8443, com a CA do campo) e por MQTT (porta 1883).',
  'ctl.open_off':
      'Só este telemóvel chega ao controlador: nada fica à escuta na rede.',
  'ctl.addresses': 'A consola, nos computadores da rede do campo:',
  'ctl.no_address':
      'Este telemóvel não está em nenhuma rede Wi-Fi: liga o hotspot ou '
      'junta-te à rede do campo.',
  'ctl.ca': 'Impressão digital da CA do campo',
  'ctl.ca_hint':
      'Vai no cartaz de check-in: os telemóveis de quem joga confirmam-na.',
  'ctl.wifi': 'Wi-Fi do campo',
  'ctl.wifi_unavailable': 'Não é possível ver o Wi-Fi neste telemóvel.',
  'ctl.wifi_off': 'Wi-Fi desligado',
  'ctl.wifi_network': 'Na rede {ssid}',
  'ctl.wifi_unknown': 'Numa rede Wi-Fi (o nome precisa da localização)',
  'ctl.hotspot_on': 'Hotspot ligado',
  'ctl.hotspot_off': 'Hotspot desligado',
  'ctl.hotspot_unknown': 'Hotspot: estado desconhecido',
  'ctl.hotspot_settings': 'Definições do hotspot',
  'ctl.wifi_settings': 'Definições de Wi-Fi',
  'ctl.local_intro':
      'Sem router nem hotspot? O telemóvel pode criar uma rede só para este '
      'jogo (o Android escolhe o nome e a palavra-passe e muda-os de cada '
      'vez: não os ponhas no cartaz).',
  'ctl.local_start': 'Criar uma rede para o jogo',
  'ctl.local_stop': 'Desligar a rede do jogo',
  'ctl.local_on': 'Rede do jogo: {ssid}',
  'ctl.local_password': 'Palavra-passe: {password}',
  'ctl.local_qr':
      'Código QR para entrar na rede {ssid}: quem joga lê-o com a câmara.',
  'ctl.local_error_permission':
      'Falta a permissão de dispositivos próximos (ou de localização).',
  'ctl.local_error_location_off': 'Liga a localização e tenta outra vez.',
  'ctl.local_error_incompatible_mode':
      'Este telemóvel não cria a rede enquanto está noutra rede Wi-Fi ou com '
      'o hotspot ligado.',
  'ctl.local_error_tethering_disallowed':
      'Este telemóvel não deixa partilhar a ligação.',
  'ctl.local_error_no_channel': 'Não há um canal Wi-Fi livre.',
  'ctl.local_error_generic': 'O Android não criou a rede.',
  'ctl.local_error_unavailable': 'Não é possível criar redes neste telemóvel.',
  'ctl.radio': 'Rádio',
  'ctl.radio_none': 'Sem rádio: só dispositivos de jogo por Wi-Fi',
  'ctl.radio_pod': 'Módulo de E/S: {name}',
  'ctl.radio_hint':
      'As caixas do campo precisam de um módulo de E/S ligado por USB ou '
      'Bluetooth.',
  'ctl.radio_locked': 'Para mudar o rádio, para o controlador.',
  'ctl.radio_up': 'Rádio ligado',
  'ctl.radio_down': 'Rádio em baixo',
  'ctl.radio_connecting': 'A ligar ao rádio…',
  'ctl.pod_forget': 'Desligar o módulo',
  'ctl.codes': 'Códigos de acesso',
  'ctl.codes_hint':
      'A consola pede um destes. O da organização manda no jogo: não o '
      'mostres a quem joga.',
  'ctl.code_gm': 'Código da organização',
  'ctl.code_read': 'Código só de leitura (marcador)',
  // Slice S7c: the field card written by this phone's NFC.
  'ctl.card': 'Cartão de campo',
  'ctl.card_hint':
      'As caixas novas entram neste campo com o cartão de campo: escreve-o '
      'num cartão NTAG215 ou NTAG216 e encosta-o uma vez a cada caixa nova. '
      'As caixas com ecrã também podem ser emparelhadas pelo código que '
      'mostram (separador Adotar da consola).',
  'ctl.card_write': 'Escrever o cartão de campo',
  'ctl.card_warn_title': 'O segredo-mestre do campo',
  'ctl.card_warn':
      'Este cartão leva a chave de entrada do campo: quem o tiver pode '
      'fazer cartões de entrada para as caixas deste campo e ler as chaves '
      'dos jogos seguintes enviadas por rádio. Guarda-o fechado à chave; se '
      'se perder ou for copiado, o campo precisa de uma chave nova.',
  'ctl.card_write_go': 'Escrever o cartão',
  'ctl.card_done': 'Cartão de campo escrito (campo {fingerprint}).',
  'ctl.card_failed': 'Não foi possível fazer o cartão de campo: tenta de novo.',
  'ctl.tags': 'Etiquetas de quem joga',
  'ctl.tags_hint':
      'Escreve as etiquetas NFC assinadas do jogo em curso com o NFC deste '
      'telemóvel. A chave do jogo fica neste telemóvel.',
  'ctl.tags_none':
      'Começa primeiro um jogo: as etiquetas são assinadas com a chave do '
      'jogo em curso.',
  'ctl.tags_open': 'Escrever etiquetas de quem joga',
  'ctl.firmware': 'Atualizações de firmware',
  'ctl.fw_keys': 'Chaves das versões de firmware',
  'ctl.fw_keys_none':
      'Nenhuma: este controlador não aceita versões de firmware para as '
      'caixas.',
  'ctl.fw_keys_set': '{n} chave(s): aceita as versões que assinam.',
  'ctl.fw_keys_hint':
      'As metades públicas das chaves de versão (base64, 44 caracteres '
      'cada), uma por linha, como em [firmware] release_keys do Pi. As '
      'caixas voltam a verificar cada versão com as chaves do seu próprio '
      'firmware. Um controlador ligado reinicia para as usar.',
  'ctl.fw_keys_bad':
      'Cada chave tem 44 caracteres base64 (32 bytes); no máximo 8.',
  'ctl.code_hidden': 'Escondido',
  'ctl.show_codes': 'Mostrar os códigos',
  'ctl.hide_codes': 'Esconder os códigos',
  'ctl.copy': 'Copiar: {what}',
  'ctl.copied': 'Copiado: {what}',
  'ctl.console': 'Consola da organização',
  'ctl.open_console': 'Abrir a consola',
  'ctl.console_title': 'Consola deste controlador',
  'ctl.no_console':
      'Esta app foi feita sem os ficheiros da consola: abre-a a partir de um '
      'computador.',
  'ctl.poster_hint':
      'Para imprimir o cartaz de check-in, abre {url} num computador da rede '
      'do campo (separador Check-in).',
  'ctl.poster_hint_closed':
      'O cartaz de check-in precisa do controlador aberto na rede Wi-Fi do '
      'campo.',
  'ctl.notif_title': 'Atalaia: controlador de campo',
  'ctl.notif_starting': 'A arrancar…',
  'ctl.notif_idle': 'Sem jogo em curso',
  'ctl.notif_game': '{name}: {state}',
  // The phone controller's [modes] settings (slice S7b of PE24).
  'ctl_modes.title': 'Pacotes de modos',
  'ctl_modes.tile': 'Pacotes de modos (controlador de campo)',
  'ctl_modes.tile_hint': '{keys} chaves de confiança, {box} chaves das caixas',
  'ctl_modes.intro':
      'As chaves em que o controlador de campo deste telemóvel confia para pacotes de modos assinados, as chaves gravadas no firmware das caixas (o controlador só lhes oferece pacotes que aceitam), as chaves revogadas e o índice do registo: a secção [modes] de um Pi. Aplicam-se quando o controlador voltar a arrancar.',
  'ctl_modes.keys': 'Chaves de modos de confiança (uma por linha, base64)',
  'ctl_modes.box_keys': 'Chaves de modos das caixas (uma por linha, base64)',
  'ctl_modes.revoked':
      'Ids de chaves revogadas (um por linha, 16 dígitos hexadecimais)',
  'ctl_modes.index':
      'Índice do registo (um endereço https:// ou um ficheiro; opcional)',
  'ctl_modes.bad_key':
      'Linha {line}: não é uma chave de modos (base64 de 32 bytes).',
  'ctl_modes.bad_id':
      'Linha {line}: não é um id de chave (16 dígitos hexadecimais).',
  'ctl_modes.bad_index': 'O índice é um endereço https:// ou um ficheiro.',
  'ctl_modes.saved':
      'Guardado: aplica-se quando o controlador voltar a arrancar.',
  // The phone controller's slice S7 settings (PE24-118 onward).
  'ctl_site.tile':
      'Servidor do site, substituição e ATAK (controlador de campo)',
  'ctl_site.tile_hint':
      'Substituição {mode}; servidor do site {sync}; ATAK {atak}',
  'ctl_site.on': 'ligado',
  'ctl_site.off': 'desligado',
  'ctl_site.title': 'Servidor do site, substituição e ATAK',
  'ctl_site.intro':
      'O controlador de campo deste telemóvel como o controller.toml de um Pi o define: a substituição, o servidor do site do campo (os jogos, os registos e as pontuações vão para lá quando há internet; listas de inscritos, imagem do campo e biblioteca de cenários vêm de lá) e o feed para o ATAK. Aplica-se quando o controlador voltar a arrancar.',
  'ctl_site.failover': 'Substituição',
  'ctl_site.failover_auto': 'Substituição automática',
  'ctl_site.manual': 'Manual',
  'ctl_site.auto': 'Automático',
  'ctl_site.failover_hint':
      'Manual: o GM promove um controlador de reserva. Automático: um controlador de reserva assume depois de três sinais em falta (30 s). Um telemóvel a bateria cede a um Pi ligado à corrente quando ambos se candidatam.',
  'ctl_site.sync': 'Servidor do site',
  'ctl_site.sync_hint': 'Primeiro offline: um jogo nunca espera pela rede.',
  'ctl_site.url': 'Endereço (https://…)',
  'ctl_site.key': 'Chave de API do campo (do servidor do site)',
  'ctl_site.key_set': 'Chave de API {fp}… (escreve outra para a substituir)',
  'ctl_site.branding':
      'Imagem do campo, equipas guardadas e definições do check-in do servidor do site',
  'ctl_site.library':
      'Cenários e predefinições de jogo do campo do servidor do site',
  'ctl_site.remote_gm': 'GM remoto',
  'ctl_site.remote_gm_hint':
      'Os GM do campo no servidor do site podem iniciar, pausar e terminar o jogo em curso. Desligado por omissão.',
  'ctl_site.atak': 'Feed ATAK (Cursor on Target)',
  'ctl_site.atak_hint':
      'As caixas e as zonas nos mapas do ATAK, pelo Wi-Fi do campo.',
  'ctl_site.multicast': 'Endereço multicast (239.2.3.1:6969)',
  'ctl_site.staff':
      'Dispositivos ATAK da organização (anfitrião:porta, separados por vírgulas)',
  'ctl_site.players':
      'Posições dos jogadores para os dispositivos da organização (nunca para multicast)',
  'ctl_site.remote': 'ATAK remoto através do servidor do site',
  'ctl_site.remote_players':
      'Também as posições dos jogadores através do servidor do site',
  'ctl_site.bad_sync': 'Servidor do site: {why}',
  'ctl_site.bad_atak': 'ATAK: {why}',
  'apd.section': 'Filiação numa APD',
  'apd.accepts_any': 'Qualquer APD é aceite.',
  'apd.accepts': 'APD aceites: {list}',
  'apd.pick': 'A APD',
  'apd.unlisted': 'Não consta da lista',
  'apd.number': 'Número de associado',
  'apd.number_required': 'Número de associado (obrigatório)',
  'apd.expires': 'Válido até (AAAA-MM-DD)',
  'apd.expires_required': 'Válido até, AAAA-MM-DD (obrigatório)',
  'apd.date_format': '2027-01-31',
  'apd.hint': 'A app não o verifica: o marshal compara-o com o cartão.',
  'apd.need_number': 'Este campo pede o número de associado da APD.',
  'apd.need_expiry': 'Este campo pede a data de validade da filiação.',
  'apd.bad_date': 'Escreve-se a data como AAAA-MM-DD, por exemplo 2027-01-31.',
  'apd.until': 'até {date}',
  'apd.overridden': 'admitido por um marshal',
  'apd.status.valid': 'Filiação válida',
  'apd.status.expired': 'Filiação caducada',
  'apd.status.not_accepted': 'APD não aceite aqui',
  'apd.status.missing': 'Filiação em falta',
  'apd.hint_marshal': 'O marshal vai ver o cartão de associado.',
  'queue.confirm': 'Admitir',
  'site.err.membership_missing':
      'Este campo exige o número de associado da APD para a inscrição.',
  'site.err.apd_not_accepted': 'Este campo não aceita essa APD.',
  'site.err.membership_expired':
      'A filiação já terá caducado no dia deste jogo.',
  // The remote GM may see shared positions (PKD-5)
  'player.share_remote_gm':
      'Se o campo tiver um GM remoto com sessão iniciada no servidor do site, o GM remoto também vê a tua posição enquanto a partilhares. O servidor do site não a guarda.',
};
