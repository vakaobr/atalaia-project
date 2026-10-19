// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Português europeu, a língua por omissão da app (strings.dart).
library;

const Map<String, String> ptStrings = {
  // Comum
  'common.cancel': 'Cancelar',
  'common.close': 'Fechar',
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

  // Definições
  'settings.title': 'Definições',
  'settings.language': 'Língua',
  'settings.lang_pt': 'Português',
  'settings.lang_en': 'English',
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
  'player.bad_link': 'Falta o endereço ou o código de acesso.',
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
  'event.zone.neutralized': '{zone} ficou neutra',
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
      'Antes de registar medições, indica o teu nome e identificador e cria a '
      'tua chave de marshal (mais abaixo, em «Quem és»).',
  'marshal.identity': 'Quem és',
  'marshal.name': 'Nome do marshal',
  'marshal.id': 'Identificador do marshal',
  'marshal.field_id': 'Identificador do campo',
  'marshal.chrono_id': 'Identificador do cronógrafo',
  'marshal.key': 'Chave de assinatura',
  'marshal.no_key': 'Ainda não tens chave: as medições têm de ser assinadas.',
  'marshal.key_id': 'Chave pública {id}…',
  'marshal.make_key': 'Criar',
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

  // Cronógrafo
  'chrono.title': 'Cronógrafo',
  'chrono.hint':
      'Entrada e verificações durante o jogo, com o limite do campo.',
  'chrono.template': 'Limites do campo',
  'chrono.unverified':
      'Os limites «{name}» não estão verificados: vêm da pesquisa do '
      'projeto, não de uma fonte oficial. Confirma-os com as regras atuais '
      'antes de os usares.',
  'chrono.checkin': 'Entrada',
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
      'As etiquetas são assinadas com a chave do jogo, por isso cada jogo '
      'tem as suas. Escolhe o jogo com o cartão ou o código QR de entrada.',
  'tags.game': 'Escolher o jogo',
  'tags.for_game': 'Jogo {game} ({mode})',
  'tags.other_game': 'Outro jogo',
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
  'queue.waiting_confirmation': 'à espera de confirmação',
  'queue.unregistered': 'ainda sem registo',
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
      'Só durante o jogo; o controlador decide quem a vê (a organização e os marshals).',
  'player.share_on': 'A partilhar: {n} posição(ões) enviada(s)',
  'player.share_stopped':
      'A partilha parou: o jogo terminou ou o check-in mudou.',
  'player.no_location': 'Este telemóvel não tem localização.',
  'player.location_denied': 'Sem autorização para a localização.',
  'player.sharing_title': 'Atalaia: a partilhar a posição',
  'player.sharing_text': 'Durante o jogo',
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
  'player.share_hint_squads':
      'Só durante o jogo; o controlador decide quem a vê (a tua squad, se o jogo o permitir, a organização e os marshals).',
  'checkin.team_squad': '{team} › squad {squad}',
  'branding.logo': 'Logótipo de {name}',
};
